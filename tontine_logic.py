from datetime import datetime, date
from decimal import Decimal
import random

# Éviter les imports circulaires - utiliser des imports différés dans les méthodes
from extensions import db

class TontineManager:
    """Gestionnaire de la logique métier pour les cycles de tontine"""
    
    def __init__(self, db_instance=None):
        self.db = db_instance or db
    
    def _get_models(self):
        """Import différé pour éviter les imports circulaires"""
        from models import TontineCycle, TontinePosition, TontineCycleDetail, CycleBeneficiary, Member, Transaction
        return {
            'TontineCycle': TontineCycle,
            'TontinePosition': TontinePosition,
            'TontineCycleDetail': TontineCycleDetail,
            'CycleBeneficiary': CycleBeneficiary,
            'Member': Member,
            'Transaction': Transaction
        }
    
    # ============================================================
    # GESTION DES CYCLES (NOUVEAU MODÈLE)
    # ============================================================
    
    def create_cycle_detailed(self, group_type, amount_per_member, members_ids, random_order=False):
        """
        Crée un nouveau cycle de tontine détaillé (avec groupe 100 ou 200 membres)
        Utilise le nouveau modèle TontineCycleDetail
        """
        models = self._get_models()
        TontineCycleDetail = models['TontineCycleDetail']
        Member = models['Member']
        
        # CORRECTION : Utiliser le bon modèle de requête
        active_cycle = self.db.session.query(TontineCycleDetail).filter(
            TontineCycleDetail.group_type == group_type,
            TontineCycleDetail.status == 'EN_COURS'
        ).first()
        
        if active_cycle:
            raise ValueError(f"Un cycle de tontine est déjà en cours pour le groupe de {group_type} membres")
        
        # Déterminer le prochain numéro de cycle
        last_cycle = self.db.session.query(TontineCycleDetail).filter(
            TontineCycleDetail.group_type == group_type
        ).order_by(TontineCycleDetail.cycle_number.desc()).first()
        next_cycle_number = (last_cycle.cycle_number + 1) if last_cycle else 1
        
        total_members = len(members_ids)
        total_amount = Decimal(str(amount_per_member)) * total_members
        
        # Créer le cycle
        cycle = TontineCycleDetail(
            cycle_number=next_cycle_number,
            group_type=group_type,
            amount_per_member=Decimal(str(amount_per_member)),
            total_amount=total_amount,
            start_date=date.today(),
            status='EN_COURS'
        )
        self.db.session.add(cycle)
        self.db.session.flush()
        
        # Créer l'ordre des bénéficiaires
        if random_order:
            random.shuffle(members_ids)
        else:
            # Ordre par position_in_group défini dans Member
            members = self.db.session.query(Member).filter(Member.id.in_(members_ids)).order_by(Member.position_in_group).all()
            members_ids = [m.id for m in members]
        
        # Assigner les positions aux membres
        for position, member_id in enumerate(members_ids, 1):
            member = self.db.session.query(Member).get(member_id)
            if member:
                member.group_type = group_type
                member.position_in_group = position
                member.chosen_tontine_amount = Decimal(str(amount_per_member))
        
        self.db.session.commit()
        return cycle
    
    def get_next_beneficiary_detailed(self, cycle_id):
        """Récupère le prochain bénéficiaire du cycle détaillé"""
        models = self._get_models()
        TontineCycleDetail = models['TontineCycleDetail']
        CycleBeneficiary = models['CycleBeneficiary']
        Member = models['Member']
        
        cycle = self.db.session.query(TontineCycleDetail).get(cycle_id)
        if not cycle or cycle.status != 'EN_COURS':
            return None
        
        # Trouver le prochain membre qui n'a pas encore bénéficié
        benefited_member_ids = [b.member_id for b in cycle.benefits.all()]
        
        next_member = self.db.session.query(Member).filter(
            Member.group_type == cycle.group_type,
            Member.is_active == True,
            Member.id.notin_(benefited_member_ids)
        ).order_by(Member.position_in_group).first()
        
        if next_member:
            # Calculer le montant net après sanctions
            net_amount = next_member.calculate_net_benefit(cycle.total_amount)
            
            return {
                'member': next_member,
                'position': next_member.position_in_group,
                'gross_amount': float(cycle.total_amount),
                'net_amount': float(net_amount),
                'sanctions_deducted': float(cycle.total_amount - net_amount)
            }
        return None
    
    def register_benefit(self, cycle_id, payment_mode='ESPECE'):
        """
        Enregistre le bénéfice pour le prochain bénéficiaire
        """
        models = self._get_models()
        TontineCycleDetail = models['TontineCycleDetail']
        CycleBeneficiary = models['CycleBeneficiary']
        Member = models['Member']
        Transaction = models['Transaction']
        
        cycle = self.db.session.query(TontineCycleDetail).get(cycle_id)
        if not cycle:
            return {'success': False, 'message': 'Cycle non trouvé'}
        
        if cycle.status != 'EN_COURS':
            return {'success': False, 'message': 'Ce cycle n\'est pas actif'}
        
        # Récupérer le prochain bénéficiaire
        next_beneficiary_data = self.get_next_beneficiary_detailed(cycle_id)
        if not next_beneficiary_data:
            return {'success': False, 'message': 'Plus de bénéficiaires disponibles ou cycle terminé'}
        
        member = next_beneficiary_data['member']
        position = next_beneficiary_data['position']
        gross_amount = next_beneficiary_data['gross_amount']
        net_amount = next_beneficiary_data['net_amount']
        sanctions_deducted = next_beneficiary_data['sanctions_deducted']
        
        # Créer l'enregistrement du bénéfice
        beneficiary = CycleBeneficiary(
            cycle_id=cycle.id,
            member_id=member.id,
            position=position,
            gross_amount=Decimal(str(gross_amount)),
            net_amount=Decimal(str(net_amount)),
            sanctions_deducted=Decimal(str(sanctions_deducted)),
            benefit_date=date.today(),
            payment_status='PAYE',
            payment_mode=payment_mode
        )
        self.db.session.add(beneficiary)
        
        # Marquer le membre comme ayant bénéficié
        member.has_received_benefit = True
        member.amount_to_receive = Decimal(str(net_amount))
        
        # CORRECTION : type doit être 'BENEFICE_TONTINE' et non 'TONTINE'
        transaction = Transaction(
            member_id=member.id,
            type='BENEFICE_TONTINE',
            amount=Decimal(str(net_amount)),
            description=f"Bénéfice tontine - Cycle #{cycle.cycle_number} - Position {position}",
            date=date.today(),
            payment_mode=payment_mode
        )
        self.db.session.add(transaction)
        
        # Mettre à jour le cycle si terminé
        if cycle.is_complete:
            cycle.status = 'TERMINE'
            cycle.end_date = date.today()
        
        self.db.session.commit()
        
        return {
            'success': True,
            'message': f"Bénéfice enregistré pour {member.full_name} - Montant net: {net_amount:,.0f} FCFA",
            'beneficiary_name': member.full_name,
            'gross_amount': gross_amount,
            'net_amount': net_amount,
            'sanctions_deducted': sanctions_deducted,
            'cycle_complete': cycle.is_complete
        }
    
    def get_cycle_progress_detailed(self, group_type=None):
        """Retourne la progression du cycle actif"""
        models = self._get_models()
        TontineCycleDetail = models['TontineCycleDetail']
        Member = models['Member']
        
        query = self.db.session.query(TontineCycleDetail).filter(TontineCycleDetail.status == 'EN_COURS')
        if group_type:
            query = query.filter(TontineCycleDetail.group_type == group_type)
        
        active_cycle = query.first()
        if not active_cycle:
            return None
        
        beneficiaries_count = active_cycle.beneficiaries_count
        total = active_cycle.total_members
        next_beneficiary = active_cycle.get_next_beneficiary()
        
        return {
            'cycle': active_cycle,
            'drawn_count': beneficiaries_count,
            'total_count': total,
            'percentage': (beneficiaries_count / total * 100) if total > 0 else 0,
            'remaining': total - beneficiaries_count,
            'next_beneficiary': next_beneficiary.full_name if next_beneficiary else None,
            'next_beneficiary_position': next_beneficiary.position_in_group if next_beneficiary else None
        }
    
    def get_cycle_history_detailed(self, group_type=None, limit=10):
        """Récupère l'historique des cycles terminés"""
        models = self._get_models()
        TontineCycleDetail = models['TontineCycleDetail']
        CycleBeneficiary = models['CycleBeneficiary']
        
        query = self.db.session.query(TontineCycleDetail).filter(TontineCycleDetail.status == 'TERMINE')
        if group_type:
            query = query.filter(TontineCycleDetail.group_type == group_type)
        
        cycles = query.order_by(TontineCycleDetail.end_date.desc()).limit(limit).all()
        
        history = []
        for cycle in cycles:
            beneficiaries = self.db.session.query(CycleBeneficiary).filter(
                CycleBeneficiary.cycle_id == cycle.id
            ).order_by(CycleBeneficiary.position).all()
            
            history.append({
                'cycle': cycle,
                'beneficiaries': beneficiaries,
                'total_collected': float(cycle.total_amount),
                'total_distributed': sum(float(b.net_amount) for b in beneficiaries),
                'total_sanctions': sum(float(b.sanctions_deducted) for b in beneficiaries)
            })
        
        return history
    
    # ============================================================
    # GESTION DES CYCLES (ANCIEN MODÈLE - POUR COMPATIBILITÉ)
    # ============================================================
    
    def create_cycle(self, name, amount_per_member, members_ids, random_order=False):
        """
        Crée un nouveau cycle de tontine (ancien modèle - pour compatibilité)
        """
        models = self._get_models()
        TontineCycle = models['TontineCycle']
        TontinePosition = models['TontinePosition']
        Member = models['Member']
        
        # Vérifier qu'il n'y a pas de cycle actif
        active_cycle = self.db.session.query(TontineCycle).filter_by(is_active=True, status='EN_COURS').first()
        if active_cycle:
            raise ValueError("Un cycle de tontine est déjà en cours")
        
        # Créer le cycle
        cycle = TontineCycle(
            name=name,
            amount_per_member=Decimal(str(amount_per_member)),
            total_members=len(members_ids),
            start_date=date.today(),
            status='EN_COURS',
            is_active=True
        )
        self.db.session.add(cycle)
        self.db.session.flush()
        
        # Créer l'ordre des bénéficiaires
        positions = list(range(1, len(members_ids) + 1))
        
        if random_order:
            random.shuffle(positions)
        else:
            # Ordre d'inscription (par date d'enregistrement)
            members = self.db.session.query(Member).filter(Member.id.in_(members_ids)).order_by(Member.registration_date).all()
            members_ids = [m.id for m in members]
        
        # Assigner les positions
        amount_received = Decimal(str(amount_per_member)) * len(members_ids)
        
        for idx, member_id in enumerate(members_ids):
            position = TontinePosition(
                cycle_id=cycle.id,
                member_id=member_id,
                position=positions[idx] if idx < len(positions) else idx + 1,
                is_drawn=False,
                draw_date=None,
                amount_received=amount_received
            )
            self.db.session.add(position)
        
        self.db.session.commit()
        return cycle
    
    def get_next_beneficiary(self, cycle_id):
        """Récupère le prochain bénéficiaire du cycle (ancien modèle)"""
        models = self._get_models()
        TontineCycle = models['TontineCycle']
        TontinePosition = models['TontinePosition']
        Member = models['Member']
        
        cycle = self.db.session.query(TontineCycle).get(cycle_id)
        if not cycle or cycle.status != 'EN_COURS':
            return None
        
        # Trouver la prochaine position non tirée
        next_position = self.db.session.query(TontinePosition).filter_by(
            cycle_id=cycle_id,
            is_drawn=False
        ).order_by(TontinePosition.position).first()
        
        if next_position:
            member = self.db.session.query(Member).get(next_position.member_id)
            return {
                'member': member,
                'position': next_position.position,
                'amount': float(next_position.amount_received)
            }
        return None
    
    def make_draw(self, cycle_id):
        """Effectue le tirage pour le bénéficiaire actuel (ancien modèle)"""
        models = self._get_models()
        TontineCycle = models['TontineCycle']
        TontinePosition = models['TontinePosition']
        Transaction = models['Transaction']
        Member = models['Member']
        
        cycle = self.db.session.query(TontineCycle).get(cycle_id)
        if not cycle:
            return {'success': False, 'message': 'Cycle non trouvé'}
        
        if cycle.status != 'EN_COURS':
            return {'success': False, 'message': 'Ce cycle n\'est pas actif'}
        
        # Récupérer le prochain bénéficiaire
        next_draw = self.get_next_beneficiary(cycle_id)
        if not next_draw:
            return {'success': False, 'message': 'Plus de bénéficiaires disponibles'}
        
        # Marquer le tirage comme effectué
        position = self.db.session.query(TontinePosition).filter_by(
            cycle_id=cycle_id,
            position=next_draw['position']
        ).first()
        
        if position:
            position.is_drawn = True
            position.draw_date = date.today()
            
            # Enregistrer la transaction de versement
            # CORRECTION : type 'BENEFICE_TONTINE' au lieu de 'TONTINE'
            transaction = Transaction(
                member_id=position.member_id,
                type='BENEFICE_TONTINE',
                amount=position.amount_received,
                description=f"Versement tontine - Cycle {cycle.name} - Tirage #{position.position}",
                date=date.today(),
                payment_mode='ESPECE'
            )
            self.db.session.add(transaction)
            
            # Mettre à jour le compteur de tirages
            cycle.current_draw_position = position.position
            
            # Vérifier si le cycle est terminé
            remaining = self.db.session.query(TontinePosition).filter_by(
                cycle_id=cycle_id, is_drawn=False
            ).count()
            if remaining == 0:
                cycle.status = 'TERMINE'
                cycle.end_date = date.today()
                cycle.is_active = False
            
            self.db.session.commit()
            
            member = self.db.session.query(Member).get(position.member_id)
            return {
                'success': True,
                'message': f"Tirage effectué pour {member.full_name} - Montant: {float(position.amount_received):,.0f} FCFA",
                'beneficiary_name': member.full_name,
                'amount': float(position.amount_received)
            }
        
        return {'success': False, 'message': 'Erreur lors du tirage'}
    
    def complete_cycle(self, cycle_id):
        """Termine un cycle de tontine (ancien modèle)"""
        models = self._get_models()
        TontineCycle = models['TontineCycle']
        TontinePosition = models['TontinePosition']
        
        cycle = self.db.session.query(TontineCycle).get(cycle_id)
        if not cycle:
            return {'success': False, 'message': 'Cycle non trouvé'}
        
        # Vérifier que tous les tirages ont été effectués
        remaining = self.db.session.query(TontinePosition).filter_by(
            cycle_id=cycle_id, is_drawn=False
        ).count()
        if remaining > 0:
            return {'success': False, 'message': f'Impossible de clôturer: {remaining} tirage(s) restant(s)'}
        
        cycle.status = 'TERMINE'
        cycle.end_date = date.today()
        cycle.is_active = False
        self.db.session.commit()
        
        return {'success': True, 'message': 'Cycle clôturé avec succès'}
    
    def get_cycle_progress(self):
        """Retourne la progression du cycle actif (ancien modèle)"""
        models = self._get_models()
        TontineCycle = models['TontineCycle']
        TontinePosition = models['TontinePosition']
        
        active_cycle = self.db.session.query(TontineCycle).filter_by(is_active=True, status='EN_COURS').first()
        if not active_cycle:
            return None
        
        drawn = self.db.session.query(TontinePosition).filter_by(
            cycle_id=active_cycle.id, is_drawn=True
        ).count()
        total = active_cycle.total_members
        
        return {
            'cycle': active_cycle,
            'drawn_count': drawn,
            'total_count': total,
            'percentage': (drawn / total * 100) if total > 0 else 0,
            'remaining': total - drawn
        }
    
    def get_cycle_history(self, limit=10):
        """Récupère l'historique des cycles terminés (ancien modèle)"""
        models = self._get_models()
        TontineCycle = models['TontineCycle']
        TontinePosition = models['TontinePosition']
        
        cycles = self.db.session.query(TontineCycle).filter_by(status='TERMINE').order_by(
            TontineCycle.end_date.desc()
        ).limit(limit).all()
        
        history = []
        for cycle in cycles:
            positions = self.db.session.query(TontinePosition).filter_by(
                cycle_id=cycle.id
            ).order_by(TontinePosition.position).all()
            
            history.append({
                'cycle': cycle,
                'positions': positions,
                'total_collected': float(cycle.amount_per_member * cycle.total_members)
            })
        
        return history
    
    # ============================================================
    # MÉTHODES UTILITAIRES
    # ============================================================
    
    def get_all_active_cycles(self):
        """Récupère tous les cycles actifs (ancien et nouveau modèle)"""
        models = self._get_models()
        TontineCycle = models['TontineCycle']
        TontineCycleDetail = models['TontineCycleDetail']
        
        cycles = {
            'old_cycles': self.db.session.query(TontineCycle).filter_by(status='EN_COURS', is_active=True).all(),
            'new_cycles': self.db.session.query(TontineCycleDetail).filter_by(status='EN_COURS').all()
        }
        return cycles
    
    def can_start_new_cycle(self, group_type=None):
        """
        Vérifie si on peut démarrer un nouveau cycle
        """
        models = self._get_models()
        TontineCycle = models['TontineCycle']
        TontineCycleDetail = models['TontineCycleDetail']
        
        if group_type:
            active = self.db.session.query(TontineCycleDetail).filter_by(
                group_type=group_type, status='EN_COURS'
            ).first()
            return active is None
        else:
            active = self.db.session.query(TontineCycle).filter_by(
                is_active=True, status='EN_COURS'
            ).first()
            return active is None
    
    def get_statistics(self):
        """Retourne les statistiques des cycles"""
        models = self._get_models()
        TontineCycle = models['TontineCycle']
        TontineCycleDetail = models['TontineCycleDetail']
        CycleBeneficiary = models['CycleBeneficiary']
        
        # Statistiques nouveau modèle
        total_cycles_new = self.db.session.query(TontineCycleDetail).count()
        completed_cycles_new = self.db.session.query(TontineCycleDetail).filter_by(status='TERMINE').count()
        active_cycles_new = self.db.session.query(TontineCycleDetail).filter_by(status='EN_COURS').count()
        
        # Statistiques ancien modèle
        total_cycles_old = self.db.session.query(TontineCycle).count()
        completed_cycles_old = self.db.session.query(TontineCycle).filter_by(status='TERMINE').count()
        active_cycles_old = self.db.session.query(TontineCycle).filter_by(status='EN_COURS', is_active=True).count()
        
        # Montants totaux distribués
        total_distributed = self.db.session.query(self.db.func.sum(CycleBeneficiary.net_amount)).scalar() or 0
        
        return {
            'total_cycles': total_cycles_new + total_cycles_old,
            'active_cycles': active_cycles_new + active_cycles_old,
            'completed_cycles': completed_cycles_new + completed_cycles_old,
            'total_distributed': float(total_distributed),
            'cycles_by_type': {
                '100_members': self.db.session.query(TontineCycleDetail).filter_by(group_type='100').count(),
                '200_members': self.db.session.query(TontineCycleDetail).filter_by(group_type='200').count()
            }
        }