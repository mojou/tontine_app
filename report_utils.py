# report_utils.py
from datetime import datetime
import io
import os
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from flask import send_file, Response, current_app, make_response
import csv
import tempfile

# ============================================================
# CONFIGURATION
# ============================================================

REPORTS_FOLDER = 'reports'

def ensure_reports_folder():
    """Crée le dossier reports s'il n'existe pas"""
    if not os.path.exists(REPORTS_FOLDER):
        os.makedirs(REPORTS_FOLDER)


# ============================================================
# GÉNÉRATION EXCEL
# ============================================================

def generate_excel_report(data, sheet_name, filename, multiple_sheets=None):
    """
    Génère un rapport Excel avec en-têtes pour éviter les problèmes IDM
    """
    ensure_reports_folder()
    
    output = io.BytesIO()
    
    try:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            if multiple_sheets:
                for sheet, df in multiple_sheets.items():
                    df.to_excel(writer, sheet_name=sheet[:31], index=False)
            elif isinstance(data, pd.DataFrame):
                data.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            else:
                df = pd.DataFrame(data)
                df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
        
        output.seek(0)
        
        # Sauvegarder une copie
        filepath = os.path.join(REPORTS_FOLDER, filename)
        with open(filepath, 'wb') as f:
            f.write(output.getvalue())
        
        # Créer la réponse avec des en-têtes anti-cache
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response
    except Exception as e:
        print(f"Erreur lors de la génération Excel: {e}")
        raise


# ============================================================
# GÉNÉRATION CSV
# ============================================================

def generate_csv_report(data, filename):
    """
    Génère un rapport CSV avec en-têtes anti-cache
    """
    ensure_reports_folder()
    
    output = io.StringIO()
    
    try:
        if not isinstance(data, pd.DataFrame):
            df = pd.DataFrame(data)
        else:
            df = data
        
        writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(df.columns.tolist())
        
        for _, row in df.iterrows():
            writer.writerow(row.tolist())
        
        output.seek(0)
        
        # Sauvegarder une copie
        filepath = os.path.join(REPORTS_FOLDER, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(output.getvalue())
        
        # Créer la réponse avec des en-têtes anti-cache
        response = make_response(output.getvalue().encode('utf-8-sig'))
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response
    except Exception as e:
        print(f"Erreur lors de la génération CSV: {e}")
        raise


# ============================================================
# GÉNÉRATION PDF (CORRIGÉE POUR ÉVITER IDM)
# ============================================================

def generate_pdf_report(title, data, headers, filename, landscape_mode=True, subtitle=None):
    """
    Génère un rapport PDF avec en-têtes anti-cache pour éviter IDM
    """
    ensure_reports_folder()
    
    # Utiliser un fichier temporaire pour éviter les problèmes de mémoire
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        temp_path = tmp_file.name
    
    try:
        # Choisir l'orientation
        page_size = landscape(A4) if landscape_mode else portrait(A4)
        
        doc = SimpleDocTemplate(
            temp_path, 
            pagesize=page_size,
            rightMargin=1.5*cm,
            leftMargin=1.5*cm,
            topMargin=1.5*cm,
            bottomMargin=1.5*cm
        )
        
        styles = getSampleStyleSheet()
        
        # Styles personnalisés
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#2c3e50'),
            alignment=1,
            spaceAfter=20,
            fontName='Helvetica-Bold'
        )
        
        subtitle_style = ParagraphStyle(
            'SubtitleStyle',
            parent=styles['Normal'],
            fontSize=11,
            textColor=colors.HexColor('#7f8c8d'),
            alignment=1,
            spaceAfter=15
        )
        
        date_style = ParagraphStyle(
            'DateStyle',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#95a5a6'),
            alignment=2,
            spaceAfter=15
        )
        
        header_style = ParagraphStyle(
            'HeaderStyle',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.whitesmoke,
            alignment=1,
            fontName='Helvetica-Bold'
        )
        
        cell_style = ParagraphStyle(
            'CellStyle',
            parent=styles['Normal'],
            fontSize=8,
            leading=10
        )
        
        # Liste des éléments
        elements = []
        
        # Titre
        elements.append(Paragraph(title, title_style))
        
        # Sous-titre
        if subtitle:
            elements.append(Paragraph(subtitle, subtitle_style))
        
        elements.append(Spacer(1, 5))
        
        # Date
        elements.append(Paragraph(f"Généré le: {datetime.now().strftime('%d/%m/%Y à %H:%M')}", date_style))
        elements.append(Spacer(1, 15))
        
        # Créer le tableau
        # Formater les en-têtes
        formatted_headers = [Paragraph(h, header_style) for h in headers]
        table_data = [formatted_headers]
        
        for row in data:
            formatted_row = []
            for cell in row:
                if cell is None:
                    formatted_row.append(Paragraph("", cell_style))
                else:
                    # Tronquer les longs textes
                    cell_str = str(cell)
                    if len(cell_str) > 50:
                        cell_str = cell_str[:47] + "..."
                    formatted_row.append(Paragraph(cell_str, cell_style))
            table_data.append(formatted_row)
        
        # Calculer les largeurs
        col_count = len(headers)
        available_width = page_size[0] - 3*cm
        col_width = available_width / col_count
        
        table = Table(table_data, repeatRows=1, colWidths=[col_width] * col_count)
        
        # Style du tableau
        table.setStyle(TableStyle([
            # En-tête
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            
            # Corps
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            
            # Alternance des couleurs
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ]))
        
        elements.append(table)
        
        # Pied de page
        elements.append(Spacer(1, 20))
        footer_style = ParagraphStyle(
            'FooterStyle',
            parent=styles['Normal'],
            fontSize=7,
            textColor=colors.HexColor('#95a5a6'),
            alignment=1
        )
        elements.append(Paragraph(f"Tontine Manager - {datetime.now().year}", footer_style))
        
        # Générer le PDF
        doc.build(elements)
        
        # Lire le fichier généré
        with open(temp_path, 'rb') as f:
            pdf_data = f.read()
        
        # Sauvegarder une copie
        filepath = os.path.join(REPORTS_FOLDER, filename)
        with open(filepath, 'wb') as f:
            f.write(pdf_data)
        
        # Créer la réponse avec des en-têtes anti-cache
        response = make_response(pdf_data)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        
        return response
        
    except Exception as e:
        print(f"Erreur lors de la génération PDF: {e}")
        raise
    finally:
        # Nettoyer le fichier temporaire
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass


# ============================================================
# RAPPORTS SPÉCIFIQUES
# ============================================================

def generate_cotisations_report_pdf(member_name, cotisations_data, start_date, end_date):
    """Génère un rapport PDF des cotisations"""
    headers = ['Date', 'Type', 'Montant (FCFA)', 'Mode', 'Statut']
    data = []
    
    total = 0
    for c in cotisations_data:
        data.append([
            c.date.strftime('%d/%m/%Y'),
            c.get_type_display(),
            f"{int(float(c.amount)):,}".replace(',', ' '),
            getattr(c, 'payment_mode', 'ESPECE'),
            'OK'
        ])
        total += float(c.amount)
    
    data.append(['', '', '', '', ''])
    data.append(['TOTAL', '', f"{int(total):,}".replace(',', ' '), '', ''])
    
    filename = f"cotisations_{member_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    subtitle = f"Période: {start_date} au {end_date}"
    
    return generate_pdf_report(
        title=f"Cotisations - {member_name}",
        data=data,
        headers=headers,
        filename=filename,
        subtitle=subtitle
    )


def generate_loans_report_pdf(loans_data, start_date, end_date):
    """Génère un rapport PDF des emprunts"""
    headers = ['Membre', 'Montant', 'Début', 'Fin', 'Intérêts', 'Statut']
    data = []
    
    total_loans = 0
    total_interest = 0
    
    for loan in loans_data:
        data.append([
            loan.member_name,
            f"{int(float(loan.amount)):,}".replace(',', ' '),
            loan.start_date.strftime('%d/%m/%Y'),
            loan.end_date.strftime('%d/%m/%Y'),
            f"{int(float(loan.interest)):,}".replace(',', ' '),
            loan.status
        ])
        total_loans += float(loan.amount)
        total_interest += float(loan.interest)
    
    data.append(['', '', '', '', '', ''])
    data.append(['TOTAL', f"{int(total_loans):,}".replace(',', ' '), '', '', f"{int(total_interest):,}".replace(',', ' '), ''])
    
    filename = f"emprunts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    subtitle = f"Période: {start_date} au {end_date}"
    
    return generate_pdf_report(
        title="Rapport des emprunts",
        data=data,
        headers=headers,
        filename=filename,
        subtitle=subtitle
    )


def generate_financial_report_pdf(entrees, sorties, start_date, end_date):
    """Génère un rapport financier PDF"""
    headers = ['Type', 'Montant (FCFA)', 'Nb transactions']
    data = []
    
    # Regrouper les entrées
    types = {}
    for t in entrees:
        type_key = t.get_type_display()
        types[type_key] = types.get(type_key, {'montant': 0, 'count': 0})
        types[type_key]['montant'] += float(t.amount)
        types[type_key]['count'] += 1
    
    data.append(['ENTREES', '', ''])
    for type_name, stats in types.items():
        data.append([f"  {type_name}", f"{int(stats['montant']):,}".replace(',', ' '), str(stats['count'])])
    
    total_entrees = sum(s['montant'] for s in types.values())
    data.append(['', '', ''])
    data.append(['TOTAL ENTREES', f"{int(total_entrees):,}".replace(',', ' '), ''])
    
    data.append(['', '', ''])
    data.append(['SORTIES', '', ''])
    
    # Regrouper les sorties
    types = {}
    for t in sorties:
        type_key = t.get_type_display()
        types[type_key] = types.get(type_key, {'montant': 0, 'count': 0})
        types[type_key]['montant'] += float(t.amount)
        types[type_key]['count'] += 1
    
    for type_name, stats in types.items():
        data.append([f"  {type_name}", f"{int(stats['montant']):,}".replace(',', ' '), str(stats['count'])])
    
    total_sorties = sum(s['montant'] for s in types.values())
    data.append(['', '', ''])
    data.append(['TOTAL SORTIES', f"{int(total_sorties):,}".replace(',', ' '), ''])
    
    data.append(['', '', ''])
    solde = total_entrees - total_sorties
    solde_color = 'success' if solde >= 0 else 'danger'
    data.append(['SOLDE', f"{int(solde):,}".replace(',', ' '), ''])
    
    filename = f"finances_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    subtitle = f"Période: {start_date} au {end_date}"
    
    return generate_pdf_report(
        title="Rapport financier",
        data=data,
        headers=headers,
        filename=filename,
        subtitle=subtitle
    )


def generate_sanctions_report_pdf(sanctions_data, start_date, end_date):
    """Génère un rapport PDF des sanctions"""
    headers = ['Membre', 'Type', 'Montant', 'Date', 'Statut']
    data = []
    
    total_pending = 0
    total_paid = 0
    
    for s in sanctions_data:
        data.append([
            s.member_name,
            s.type_display,
            f"{int(float(s.amount)):,}".replace(',', ' '),
            s.sanction_date.strftime('%d/%m/%Y'),
            'Payée' if s.is_paid else 'En attente'
        ])
        if s.is_paid:
            total_paid += float(s.amount)
        else:
            total_pending += float(s.amount)
    
    data.append(['', '', '', '', ''])
    data.append(['Sanctions payées', '', f"{int(total_paid):,}".replace(',', ' '), '', ''])
    data.append(['Sanctions en attente', '', f"{int(total_pending):,}".replace(',', ' '), '', ''])
    data.append(['TOTAL', '', f"{int(total_paid + total_pending):,}".replace(',', ' '), '', ''])
    
    filename = f"sanctions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    subtitle = f"Période: {start_date} au {end_date}"
    
    return generate_pdf_report(
        title="Rapport des sanctions",
        data=data,
        headers=headers,
        filename=filename,
        subtitle=subtitle
    )


def generate_tontine_cycle_report_pdf(cycle, beneficiaries):
    """Génère un rapport PDF pour un cycle de tontine terminé"""
    headers = ['Pos', 'Membre', 'Montant brut', 'Sanctions', 'Montant net', 'Date']
    data = []
    
    total_gross = 0
    total_sanctions = 0
    total_net = 0
    
    for b in beneficiaries:
        data.append([
            str(b.position),
            b.member_name,
            f"{int(float(b.gross_amount)):,}".replace(',', ' '),
            f"{int(float(b.sanctions_deducted)):,}".replace(',', ' '),
            f"{int(float(b.net_amount)):,}".replace(',', ' '),
            b.benefit_date.strftime('%d/%m/%Y')
        ])
        total_gross += float(b.gross_amount)
        total_sanctions += float(b.sanctions_deducted)
        total_net += float(b.net_amount)
    
    data.append(['', '', '', '', '', ''])
    data.append([
        'TOTAL', '',
        f"{int(total_gross):,}".replace(',', ' '),
        f"{int(total_sanctions):,}".replace(',', ' '),
        f"{int(total_net):,}".replace(',', ' '),
        ''
    ])
    
    filename = f"cycle_tontine_{cycle.cycle_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    subtitle = f"Groupe {cycle.group_type} membres - Cycle #{cycle.cycle_number}"
    
    return generate_pdf_report(
        title=f"Rapport du cycle de tontine",
        data=data,
        headers=headers,
        filename=filename,
        subtitle=subtitle
    )


# ============================================================
# EXPORTATION EXCEL SPÉCIFIQUE
# ============================================================

def export_members_to_excel(members, filename=None):
    """Exporte les membres vers Excel"""
    if filename is None:
        filename = f"membres_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    data = []
    for m in members:
        data.append({
            'ID': m.id,
            'Nom': m.last_name,
            'Prénom': m.first_name,
            'Email': m.email,
            'Téléphone': m.phone,
            'Ville': m.city or '',
            'Profession': m.profession or '',
            'Statut': m.status,
            "Statut tontine": m.tontine_status,
            "Date inscription": m.registration_date.strftime('%d/%m/%Y'),
            'Épargne': float(m.total_savings),
            'Sanctions': float(m.total_sanctions_pending)
        })
    
    df = pd.DataFrame(data)
    return generate_excel_report(df, 'Membres', filename)


def export_transactions_to_excel(transactions, filename=None):
    """Exporte les transactions vers Excel"""
    if filename is None:
        filename = f"transactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    data = []
    for t in transactions:
        data.append({
            'Date': t.date.strftime('%d/%m/%Y'),
            'Membre': t.member_name,
            'Type': t.get_type_display(),
            'Montant': float(t.amount),
            'Mode': getattr(t, 'payment_mode', 'ESPECE'),
            'Description': t.description or ''
        })
    
    df = pd.DataFrame(data)
    return generate_excel_report(df, 'Transactions', filename)


def export_loans_to_excel(loans, filename=None):
    """Exporte les emprunts vers Excel"""
    if filename is None:
        filename = f"emprunts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    data = []
    for loan in loans:
        data.append({
            'ID': loan.id,
            'Membre': loan.member_name,
            'Montant': float(loan.amount),
            'Intérêts': float(loan.interest),
            'Total à payer': float(loan.total_to_pay),
            'Payé': float(loan.amount_paid),
            'Reste': float(loan.remaining_to_pay),
            'Date début': loan.start_date.strftime('%d/%m/%Y'),
            'Date fin': loan.end_date.strftime('%d/%m/%Y'),
            'Statut': loan.status,
            'Motif': loan.purpose
        })
    
    df = pd.DataFrame(data)
    return generate_excel_report(df, 'Emprunts', filename)


# ============================================================
# UTILITAIRES
# ============================================================

def cleanup_old_reports(days=30):
    """Supprime les rapports plus vieux que 'days' jours"""
    import time
    ensure_reports_folder()
    
    now = time.time()
    cutoff = now - (days * 86400)
    
    deleted_count = 0
    for filename in os.listdir(REPORTS_FOLDER):
        filepath = os.path.join(REPORTS_FOLDER, filename)
        if os.path.getmtime(filepath) < cutoff:
            try:
                os.remove(filepath)
                deleted_count += 1
            except:
                pass
    
    return deleted_count