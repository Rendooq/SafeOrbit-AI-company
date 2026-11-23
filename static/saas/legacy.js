
        function showToast(msg, type = 'success') {
            if (!document.body) {
                document.addEventListener('DOMContentLoaded', () => showToast(msg, type), {once:true});
                return;
            }
            Swal.fire({
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 3000,
                icon: type,
                title: msg,
                background: '#ffffff',
                color: '#54546c',
                customClass: { popup: 'glass-card' }
            });
        }
        
        const urlParams = new URLSearchParams(window.location.search);
        const msg = urlParams.get('msg');
        if (msg) {
            const msgs = {
                'added': 'Запис успішно додано!',
                'saved': 'Зміни збережено!',
                'deleted': 'Запис видалено!',
                'time_taken': 'Цей час вже зайнятий!',
                'sms_sent': 'Повідомлення відправлено!',
                'added_and_synced': 'Запис додано та синхронізовано!',
                'branch_added': 'Філію створено!',
                'branch_deleted': 'Філію видалено!',
                'login_exists': 'Такий логін вже існує!',
                'broadcast_sent': 'Розсилку відправлено!',
                'saved': 'Збережено!'
            };
            showToast(msgs[msg] || msg);
            window.history.replaceState(null, null, window.location.pathname);
        }
        
        // Search functionality
        const searchInput = document.getElementById('globalSearch');
        const searchResults = document.getElementById('searchResults');
        let searchTimeout;
        
        if (searchInput) {
            searchInput.addEventListener('input', function() {
                clearTimeout(searchTimeout);
                const query = this.value.trim();
                
                if (query.length < 2) {
                    searchResults.classList.remove('active');
                    return;
                }
                
                searchTimeout = setTimeout(() => performSearch(query), 300);
            });
            
            searchInput.addEventListener('focus', function() {
                if (this.value.trim().length >= 2) {
                    searchResults.classList.add('active');
                }
            });
            
            document.addEventListener('click', function(e) {
                if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
                    searchResults.classList.remove('active');
                }
            });
        }
        
        async function performSearch(query) {
            try {
                const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
                const data = await response.json();
                displaySearchResults(data.results);
            } catch (err) {
                console.error('Search error:', err);
            }
        }
        
        function displaySearchResults(results) {
            if (!results || results.length === 0) {
                searchResults.innerHTML = '<div class="search-result-item"><div class="search-result-title">Нічого не знайдено</div></div>';
                searchResults.classList.add('active');
                return;
            }
            
            const html = results.map(r => `
                <div class="search-result-item" onclick="handleSearchResult('${r.type}', '${r.id}')">
                    <div class="search-result-title">${r.title}</div>
                    <div class="search-result-type">${r.type === 'client' ? 'Гість' : r.type === 'appointment' ? 'Запис' : 'Сервіс'}</div>
                </div>
            `).join('');
            
            searchResults.innerHTML = html;
            searchResults.classList.add('active');
        }
        
        function handleSearchResult(type, id) {
            if (type === 'client') {
                window.location.href = `/admin/klienci?id=${id}`;
            } else if (type === 'appointment') {
                const row = document.querySelector(`[data-appt-id="${id}"]`);
                if (row) row.scrollIntoView({behavior: 'smooth'});
            }
            searchResults.classList.remove('active');
        }
        
        function toggleSidebar() {
            if (window.innerWidth <= 767.98) {
                document.querySelector('.sidebar').classList.toggle('mobile-open');
            } else {
                document.querySelector('.sidebar').classList.toggle('hidden');
                document.querySelector('.main-content').classList.toggle('expanded');
                document.body.classList.toggle('sidebar-hidden');
            }
        }
        
        document.addEventListener("DOMContentLoaded", async () => {
            try {
                const res = await fetch('/admin/api/unread-updates');
                const data = await res.json();
                if(data.count > 0) {
                    const updLink = document.getElementById('menu-upd');
                    if(updLink) {
                        updLink.innerHTML += `<span class="badge bg-danger rounded-pill ms-auto" style="font-size:10px; padding: 4px 8px;">${data.count}</span>`;
                    }
                }
            } catch(e) {}
        });

        // API Key UI functions
        function toggleApiKeyVisibility(inputId, button) {
            const input = document.getElementById(inputId);
            if (input.type === "password") {
                input.type = "text";
                button.innerHTML = '<i class="fas fa-eye-slash text-info"></i>';
                button.title = "Приховати ключ";
            } else {
                input.type = "password";
                button.innerHTML = '<i class="fas fa-eye text-info"></i>';
                button.title = "Показати ключ";
            }
        }

        function copyApiKey(inputId) {
            const input = document.getElementById(inputId);
            input.type = "text"; // Temporarily show to copy
            input.select();
            document.execCommand("copy");
            input.type = "password"; // Hide again
            showToast('API ключ скопійовано!', 'success');
        }
        
        // --- GLOBAL STATE MANAGEMENT & PERFORMANCE OPTIMIZATIONS ---
        document.addEventListener('DOMContentLoaded', () => {
            const path = window.location.pathname;
            
            // 1. Відновлення активної вкладки (Запобігає скиданню після перезавантаження/збереження)
            const savedTab = localStorage.getItem('activeTab_' + path);
            if (savedTab) {
                const tabBtn = document.querySelector(`[data-bs-target="${savedTab}"]`);
                if (tabBtn) {
                    const tab = new bootstrap.Tab(tabBtn);
                    tab.show();
                }
            }

            // 2. Збереження стану вкладки
            const tabElements = document.querySelectorAll('button[data-bs-toggle="tab"], button[data-bs-toggle="pill"]');
            tabElements.forEach(el => {
                el.addEventListener('shown.bs.tab', event => {
                    const target = event.target.getAttribute('data-bs-target');
                    if(target) localStorage.setItem('activeTab_' + path, target);
                });
            });

            // 3. Глобальний Loading State для запобігання подвійних submit та зависань UI
            document.querySelectorAll('form').forEach(form => {
                if(!form.hasAttribute('onsubmit')) {
                    form.addEventListener('submit', function(e) {
                        const btn = this.querySelector('button[type="submit"], button:not([type="button"])');
                        if (btn && !btn.disabled) {
                            // Дозволяємо формі відправитись, але блокуємо UI
                            setTimeout(() => {
                                btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Завантаження...';
                                btn.disabled = true;
                                btn.style.opacity = '0.7';
                                btn.style.pointerEvents = 'none';
                            }, 10);
                        }
                    });
                }
            });
        });
    
