/**
 * Encontros Tech - JavaScript Principal
 * Funcionalidades interativas e UX aprimorada
 */

document.addEventListener('DOMContentLoaded', function() {
    // Inicializar componentes
    initEventCards();
    initFormEnhancements();
    initSearchFilters();
    initAnimations();
});

/**
 * Inicializar funcionalidades dos cards de eventos
 */
function initEventCards() {
    const eventCards = document.querySelectorAll('.event-card');
    
    eventCards.forEach(card => {
        // Adicionar efeitos de hover mais suaves
        card.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-8px) scale(1.02)';
        });
        
        card.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0) scale(1)';
        });
        
        // Gerar cores dinâmicas para o header baseado nas tecnologias
        const techBadges = card.querySelectorAll('.tech-badge');
        if (techBadges.length > 0) {
            const header = card.querySelector('.event-card-header');
            if (header) {
                const colors = getTechColors(techBadges);
                header.style.background = `linear-gradient(135deg, ${colors[0]} 0%, ${colors[1]} 100%)`;
            }
        }
    });
}

/**
 * Obter cores baseadas nas tecnologias do evento
 */
function getTechColors(techBadges) {
    const techColorMap = {
        'python': ['#3776ab', '#4b8bbe'],
        'javascript': ['#f7df1e', '#d4ac0d'],
        'react': ['#61dafb', '#0d7377'],
        'node': ['#68a063', '#4d7c0f'],
        'docker': ['#0db7ed', '#0284c7'],
        'kubernetes': ['#326ce5', '#1d4ed8'],
        'aws': ['#ff9900', '#ea580c'],
        'java': ['#ed8b00', '#c2410c'],
        'go': ['#00add8', '#0891b2'],
        'rust': ['#000000', '#374151']
    };
    
    const defaultColors = ['#1a73e8', '#6c5ce7'];
    
    // Pegar a primeira tecnologia encontrada
    for (let badge of techBadges) {
        const techName = badge.textContent.toLowerCase();
        for (let [key, colors] of Object.entries(techColorMap)) {
            if (techName.includes(key)) {
                return colors;
            }
        }
    }
    
    return defaultColors;
}

/**
 * Melhorar experiência dos formulários
 */
function initFormEnhancements() {
    // Aplicar classes modernas aos formulários existentes
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.classList.add('form-modern');
    });
    
    // Adicionar feedback visual nos campos
    const inputs = document.querySelectorAll('.form-control, .form-select');
    inputs.forEach(input => {
        input.addEventListener('focus', function() {
            this.parentElement.classList.add('focused');
        });
        
        input.addEventListener('blur', function() {
            this.parentElement.classList.remove('focused');
        });
        
        // Validação visual em tempo real
        input.addEventListener('input', function() {
            if (this.checkValidity()) {
                this.classList.remove('is-invalid');
                this.classList.add('is-valid');
            } else {
                this.classList.remove('is-valid');
                this.classList.add('is-invalid');
            }
        });
    });
}

/**
 * Melhorar filtros de busca com feedback visual
 */
function initSearchFilters() {
    const searchForm = document.querySelector('form[method="get"]');
    if (!searchForm) return;
    
    const searchInput = searchForm.querySelector('input[name="search"]');
    const technologySelect = searchForm.querySelector('select[name="technology"]');
    
    // Adicionar indicador de busca ativa
    if (searchInput && searchInput.value) {
        searchInput.parentElement.classList.add('has-search');
    }
    
    if (technologySelect && technologySelect.value) {
        technologySelect.parentElement.classList.add('has-filter');
    }
    
    // Auto-submit após delay para melhor UX
    let searchTimeout;
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                // Opcional: auto-submit da busca
                // searchForm.submit();
            }, 500);
        });
    }
}

/**
 * Inicializar animações e transições
 */
function initAnimations() {
    // Fade in dos elementos quando carregam
    const animatedElements = document.querySelectorAll('.event-card, .main-container, .filters-section');
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('fade-in');
            }
        });
    }, {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    });
    
    animatedElements.forEach(el => {
        observer.observe(el);
    });
    
    // Smooth scroll para links internos
    const links = document.querySelectorAll('a[href^="#"]');
    links.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({ behavior: 'smooth' });
            }
        });
    });
}

/**
 * Aplicar badges de tecnologia com cores dinâmicas
 */
function applyTechBadgeColors() {
    const techBadges = document.querySelectorAll('.tech-badge');
    
    techBadges.forEach(badge => {
        const techName = badge.textContent.toLowerCase().trim();
        badge.setAttribute('data-tech', techName);
    });
}

/**
 * Função utilitária para mostrar loading states
 */
function showLoading(element, text = 'Carregando...') {
    const originalContent = element.innerHTML;
    element.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>${text}`;
    element.disabled = true;
    
    return () => {
        element.innerHTML = originalContent;
        element.disabled = false;
    };
}

/**
 * Função para mostrar notificações toast
 */
function showToast(message, type = 'success') {
    // Criar elemento toast se não existir
    let toastContainer = document.querySelector('.toast-container');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
        document.body.appendChild(toastContainer);
    }
    
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${type === 'success' ? 'success' : type === 'error' ? 'danger' : 'primary'} border-0`;
    toast.setAttribute('role', 'alert');
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${message}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    
    toastContainer.appendChild(toast);
    
    // Bootstrap toast
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
    
    // Remover do DOM após ser fechado
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
}

// Executar algumas inicializações quando o documento estiver pronto
document.addEventListener('DOMContentLoaded', function() {
    applyTechBadgeColors();
    initAccessibilityFeatures();
    initPerformanceOptimizations();
});

/**
 * Inicializar recursos de acessibilidade
 */
function initAccessibilityFeatures() {
    // Adicionar suporte a navegação por teclado para cards clicáveis
    const clickableCards = document.querySelectorAll('.event-card[onclick]');
    clickableCards.forEach(card => {
        card.setAttribute('tabindex', '0');
        card.setAttribute('role', 'button');
        card.setAttribute('aria-label', 'Ver detalhes do evento');
        
        card.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                card.click();
            }
        });
    });
    
    // Melhorar labels dos formulários
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        const requiredFields = form.querySelectorAll('[required]');
        requiredFields.forEach(field => {
            const label = form.querySelector(`label[for="${field.id}"]`);
            if (label && !label.textContent.includes('*')) {
                label.innerHTML = label.innerHTML.replace(' *', '') + ' <span class="text-danger">*</span>';
            }
        });
    });
    
    // Adicionar skip links para navegação
    if (!document.querySelector('.skip-link')) {
        const skipLink = document.createElement('a');
        skipLink.href = '#main-content';
        skipLink.className = 'skip-link sr-only sr-only-focusable';
        skipLink.textContent = 'Pular para o conteúdo principal';
        skipLink.style.cssText = `
            position: absolute;
            top: -40px;
            left: 6px;
            background: var(--primary-blue);
            color: white;
            padding: 8px;
            text-decoration: none;
            border-radius: 4px;
            z-index: 1000;
        `;
        document.body.insertBefore(skipLink, document.body.firstChild);
        
        skipLink.addEventListener('focus', () => {
            skipLink.style.top = '6px';
        });
        
        skipLink.addEventListener('blur', () => {
            skipLink.style.top = '-40px';
        });
    }
}

/**
 * Otimizações de performance
 */
function initPerformanceOptimizations() {
    // Lazy loading para animações
    if ('IntersectionObserver' in window) {
        const lazyAnimations = document.querySelectorAll('[data-animate]');
        const animationObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('fade-in');
                    animationObserver.unobserve(entry.target);
                }
            });
        }, { rootMargin: '50px' });
        
        lazyAnimations.forEach(el => animationObserver.observe(el));
    }
    
    // Debounce para campos de busca
    const searchInputs = document.querySelectorAll('input[name="search"]');
    searchInputs.forEach(input => {
        let searchTimeout;
        input.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            const value = this.value;
            
            // Visual feedback
            if (value.length > 0) {
                this.parentElement.classList.add('has-content');
            } else {
                this.parentElement.classList.remove('has-content');
            }
            
            // Auto-submit após 800ms (opcional - comentado para não interferir)
            // searchTimeout = setTimeout(() => {
            //     if (value.length >= 2 || value.length === 0) {
            //         this.form.submit();
            //     }
            // }, 800);
        });
    });
    
    // Prefetch para navegação
    const internalLinks = document.querySelectorAll('a[href^="/"]');
    internalLinks.forEach(link => {
        link.addEventListener('mouseenter', () => {
            const prefetchLink = document.createElement('link');
            prefetchLink.rel = 'prefetch';
            prefetchLink.href = link.href;
            document.head.appendChild(prefetchLink);
        }, { once: true });
    });
}

/**
 * Melhorias de UX para formulários
 */
function enhanceFormUX() {
    const forms = document.querySelectorAll('form');
    
    forms.forEach(form => {
        // Validação em tempo real melhorada
        const inputs = form.querySelectorAll('input, textarea, select');
        
        inputs.forEach(input => {
            let validationTimeout;
            
            input.addEventListener('input', function() {
                clearTimeout(validationTimeout);
                
                // Remover estados anteriores
                this.classList.remove('is-valid', 'is-invalid');
                
                // Validar após delay
                validationTimeout = setTimeout(() => {
                    if (this.value.trim() !== '') {
                        if (this.checkValidity()) {
                            this.classList.add('is-valid');
                        } else {
                            this.classList.add('is-invalid');
                        }
                    }
                }, 300);
            });
            
            // Limpar validação quando campo está vazio
            input.addEventListener('blur', function() {
                if (this.value.trim() === '' && !this.hasAttribute('required')) {
                    this.classList.remove('is-valid', 'is-invalid');
                }
            });
        });
        
        // Prevenir duplo submit
        form.addEventListener('submit', function() {
            const submitBtn = this.querySelector('button[type="submit"]');
            if (submitBtn && !submitBtn.disabled) {
                setTimeout(() => {
                    submitBtn.disabled = true;
                    submitBtn.style.opacity = '0.6';
                }, 100);
            }
        });
    });
}

/**
 * Gerenciador de temas (preparação para dark mode futuro)
 */
const themeManager = {
    init() {
        // Detectar preferência do sistema
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)');
        this.updateTheme(prefersDark.matches);
        
        // Ouvir mudanças na preferência
        prefersDark.addListener((e) => this.updateTheme(e.matches));
    },
    
    updateTheme(isDark) {
        document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    }
};

// Inicializar melhorias adicionais
document.addEventListener('DOMContentLoaded', function() {
    enhanceFormUX();
    themeManager.init();
    
    // Adicionar classe para animações após carregamento
    setTimeout(() => {
        document.body.classList.add('loaded');
    }, 100);
});

// Service Worker para cache (preparação futura)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        // navigator.serviceWorker.register('/sw.js')
        //     .then(registration => console.log('SW registered'))
        //     .catch(error => console.log('SW registration failed'));
    });
}