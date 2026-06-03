/**
 * TONTINE MANAGEMENT SYSTEM
 * JavaScript pour interactions dynamiques et appels AJAX
 */

// Attendre que le DOM soit chargé
document.addEventListener('DOMContentLoaded', function() {
    
    // ============================================
    // GESTION DES ALERTES
    // ============================================
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        const closeBtn = alert.querySelector('.alert-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                alert.style.opacity = '0';
                setTimeout(() => alert.remove(), 300);
            });
        }
        
        // Auto-fermeture après 5 secondes
        setTimeout(() => {
            if (alert) {
                alert.style.opacity = '0';
                setTimeout(() => alert.remove(), 300);
            }
        }, 5000);
    });
    
    // ============================================
    // CONFIRMATIONS DE SUPPRESSION
    // ============================================
    const deleteButtons = document.querySelectorAll('.btn-delete, [data-confirm]');
    deleteButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            const message = btn.getAttribute('data-confirm') || 'Êtes-vous sûr de vouloir effectuer cette action ?';
            if (!confirm(message)) {
                e.preventDefault();
                return false;
            }
        });
    });
    
    // ============================================
    // RECHERCHE EN TEMPS RÉEL
    // ============================================
    const searchInput = document.querySelector('.search-input');
    if (searchInput) {
        let searchTimeout;
        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                const searchValue = this.value;
                const currentUrl = new URL(window.location.href);
                currentUrl.searchParams.set('search', searchValue);
                window.location.href = currentUrl.toString();
            }, 500);
        });
    }
    
    // ============================================
    // FILTRES DROPDOWN
    // ============================================
    const filterSelect = document.querySelector('.filter-select');
    if (filterSelect) {
        filterSelect.addEventListener('change', function() {
            const filterValue = this.value;
            const currentUrl = new URL(window.location.href);
            if (filterValue) {
                currentUrl.searchParams.set('type', filterValue);
            } else {
                currentUrl.searchParams.delete('type');
            }
            window.location.href = currentUrl.toString();
        });
    }
    
    // ============================================
    // VALIDATION DE FORMULAIRES
    // ============================================
    const forms = document.querySelectorAll('form[data-validate]');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            let isValid = true;
            const requiredFields = this.querySelectorAll('[required]');
            
            requiredFields.forEach(field => {
                if (!field.value.trim()) {
                    isValid = false;
                    field.classList.add('error');
                    showFieldError(field, 'Ce champ est requis');
                } else {
                    field.classList.remove('error');
                    removeFieldError(field);
                }
                
                // Validation email
                if (field.type === 'email' && field.value) {
                    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                    if (!emailRegex.test(field.value)) {
                        isValid = false;
                        showFieldError(field, 'Email invalide');
                    }
                }
                
                // Validation téléphone
                if (field.type === 'tel' && field.value) {
                    const phoneRegex = /^[0-9+\-\s]{8,}$/;
                    if (!phoneRegex.test(field.value)) {
                        isValid = false;
                        showFieldError(field, 'Numéro de téléphone invalide');
                    }
                }
            });
            
            if (!isValid) {
                e.preventDefault();
            }
        });
    });
    
    function showFieldError(field, message) {
        let errorDiv = field.parentElement.querySelector('.field-error');
        if (!errorDiv) {
            errorDiv = document.createElement('small');
            errorDiv.className = 'field-error';
            field.parentElement.appendChild(errorDiv);
        }
        errorDiv.textContent = message;
        errorDiv.style.color = '#e74c3c';
        errorDiv.style.fontSize = '0.8rem';
        errorDiv.style.marginTop = '5px';
        errorDiv.style.display = 'block';
    }
    
    function removeFieldError(field) {
        const errorDiv = field.parentElement.querySelector('.field-error');
        if (errorDiv) {
            errorDiv.remove();
        }
    }
    
    // ============================================
    // CHARGEMENT DYNAMIQUE (AJAX)
    // ============================================
    
    // Remboursement de prêt en AJAX
    const repayForms = document.querySelectorAll('.repay-form');
    repayForms.forEach(form => {
        form.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            const actionUrl = this.action;
            const submitBtn = this.querySelector('button[type="submit"]');
            const originalText = submitBtn.innerHTML;
            
            // Afficher le chargement
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="loading"></span> Traitement...';
            
            try {
                const response = await fetch(actionUrl, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });
                
                const data = await response.json();
                
                if (data.success) {
                    showNotification(data.message, 'success');
                    setTimeout(() => window.location.reload(), 1500);
                } else {
                    showNotification(data.message, 'error');
                }
            } catch (error) {
                showNotification('Erreur lors du traitement', 'error');
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalText;
            }
        });
    });
    
    // ============================================
    // NOTIFICATIONS TOAST
    // ============================================
    function showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = `
            <div class="notification-content">
                <span class="notification-message">${message}</span>
                <button class="notification-close">&times;</button>
            </div>
        `;
        
        notification.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: ${type === 'success' ? '#27ae60' : type === 'error' ? '#e74c3c' : '#3498db'};
            color: white;
            padding: 15px 20px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            z-index: 9999;
            animation: slideIn 0.3s ease;
        `;
        
        document.body.appendChild(notification);
        
        const closeBtn = notification.querySelector('.notification-close');
        closeBtn.addEventListener('click', () => notification.remove());
        
        setTimeout(() => {
            if (notification) notification.remove();
        }, 4000);
    }
    
    // ============================================
    // GRAPHIQUES (Dashboard)
    // ============================================
    const chartCanvas = document.getElementById('transactionsChart');
    if (chartCanvas && typeof Chart !== 'undefined') {
        fetch('/api/transactions-summary')
            .then(response => response.json())
            .then(data => {
                new Chart(chartCanvas, {
                    type: 'bar',
                    data: {
                        labels: data.labels,
                        datasets: [{
                            label: 'Transactions',
                            data: data.values,
                            backgroundColor: '#3498db',
                            borderColor: '#2980b9',
                            borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: true,
                        scales: {
                            y: {
                                beginAtZero: true
                            }
                        }
                    }
                });
            })
            .catch(error => console.error('Erreur chargement graphique:', error));
    }
    
    // ============================================
    // TIRAGE AU SORT ALÉATOIRE
    // ============================================
    const randomDrawBtn = document.querySelector('#randomDrawBtn');
    if (randomDrawBtn) {
        randomDrawBtn.addEventListener('click', async function() {
            const cycleId = this.dataset.cycleId;
            
            if (confirm('Effectuer un tirage au sort ?')) {
                const loading = document.createElement('div');
                loading.className = 'loading-overlay';
                loading.innerHTML = '<div class="loading"></div>';
                document.body.appendChild(loading);
                
                try {
                    const response = await fetch(`/tontine/cycles/${cycleId}/random-draw`, {
                        method: 'POST',
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    });
                    
                    const data = await response.json();
                    showNotification(data.message, data.success ? 'success' : 'error');
                    
                    if (data.success) {
                        setTimeout(() => window.location.reload(), 1500);
                    }
                } catch (error) {
                    showNotification('Erreur lors du tirage', 'error');
                } finally {
                    loading.remove();
                }
            }
        });
    }
    
    // ============================================
    // EXPORT DE DONNÉES
    // ============================================
   // const exportBtns = document.querySelectorAll('.btn-export');
    //exportBtns.forEach(btn => {
        //btn.addEventListener('click', function(e) {
           // const exportType = this.dataset.export;
           // const currentUrl = window.location.href;
           // window.location.href = `${currentUrl}?export=${exportType}`;
       // });
    //});
    
    // ============================================
    // TOOLTIPS
    // ============================================
    const tooltips = document.querySelectorAll('[data-tooltip]');
    tooltips.forEach(element => {
        element.addEventListener('mouseenter', function(e) {
            const tooltipText = this.dataset.tooltip;
            const tooltip = document.createElement('div');
            tooltip.className = 'tooltip';
            tooltip.textContent = tooltipText;
            tooltip.style.cssText = `
                position: absolute;
                background: #333;
                color: white;
                padding: 5px 10px;
                border-radius: 5px;
                font-size: 0.8rem;
                z-index: 1000;
                white-space: nowrap;
            `;
            
            const rect = this.getBoundingClientRect();
            tooltip.style.top = `${rect.top - 30 + window.scrollY}px`;
            tooltip.style.left = `${rect.left + (rect.width / 2) - (tooltip.offsetWidth / 2)}px`;
            
            document.body.appendChild(tooltip);
            
            this.addEventListener('mouseleave', () => tooltip.remove(), { once: true });
        });
    });
    
    // ============================================
    // MODALES
    // ============================================
    const modalTriggers = document.querySelectorAll('[data-modal]');
    modalTriggers.forEach(trigger => {
        trigger.addEventListener('click', function() {
            const modalId = this.dataset.modal;
            const modal = document.getElementById(modalId);
            if (modal) {
                modal.style.display = 'flex';
                
                const closeBtn = modal.querySelector('.modal-close');
                if (closeBtn) {
                    closeBtn.addEventListener('click', () => {
                        modal.style.display = 'none';
                    });
                }
                
                modal.addEventListener('click', (e) => {
                    if (e.target === modal) {
                        modal.style.display = 'none';
                    }
                });
            }
        });
    });
    
    // ============================================
    // MISE À JOUR AUTO DES MONTANTS
    // ============================================
    const amountInput = document.querySelector('#amount');
    const interestDisplay = document.querySelector('#interest-display');
    
    if (amountInput && interestDisplay) {
        amountInput.addEventListener('input', function() {
            const amount = parseFloat(this.value) || 0;
            const interest = amount * 0.10;
            interestDisplay.textContent = `${interest.toLocaleString()} CFA`;
        });
    }
    
    // ============================================
    // MASQUER/AFFICHER MOT DE PASSE
    // ============================================
    const togglePasswordBtns = document.querySelectorAll('.toggle-password');
    togglePasswordBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const passwordInput = this.previousElementSibling;
            const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
            passwordInput.setAttribute('type', type);
            this.textContent = type === 'password' ? '👁️' : '🔒';
        });
    });
});

// ============================================
// FONCTIONS UTILES GLOBALES
// ============================================

// Formatage des nombres
function formatNumber(number) {
    return new Intl.NumberFormat('fr-FR').format(number);
}

// Formatage des dates
function formatDate(dateString) {
    const options = { year: 'numeric', month: 'long', day: 'numeric' };
    return new Date(dateString).toLocaleDateString('fr-FR', options);
}

// Calcul de jours restants
function daysRemaining(endDate) {
    const today = new Date();
    const end = new Date(endDate);
    const diffTime = end - today;
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays;
}

// Animation de compteur
function animateCounter(element, target) {
    let current = 0;
    const increment = target / 50;
    const timer = setInterval(() => {
        current += increment;
        if (current >= target) {
            clearInterval(timer);
            current = target;
        }
        element.textContent = formatNumber(Math.floor(current));
    }, 20);
}

// Appliquer les animations de compteur
document.querySelectorAll('.stat-value[data-target]').forEach(el => {
    const target = parseInt(el.dataset.target);
    animateCounter(el, target);
});

// Ajout des styles d'animation
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    .field-error {
        animation: slideIn 0.3s ease;
    }
    
    .loading-overlay {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
    }
    
    .error {
        border-color: #e74c3c !important;
    }
`;
document.head.appendChild(style);