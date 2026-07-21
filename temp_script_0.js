
        const chatHistory = document.getElementById('chatHistory');
        const chatForm = document.getElementById('chatForm');
        const msgInput = document.getElementById('msgInput');
        const inputPhoneNumber = document.getElementById('inputPhoneNumber');
        const btnReset = document.getElementById('btnReset');
        const btnRefresh = document.getElementById('btnRefresh');

        // Referencias a los slots del sidebar
        const slotFecha = document.getElementById('slotFecha');
        const slotAmbiente = document.getElementById('slotAmbiente');
        const slotInvitados = document.getElementById('slotInvitados');
        const slotDispo = document.getElementById('slotDispo');
        const slotFallas = document.getElementById('slotFallas');

        // Cargar slots en UI
        async function actualizarSlotsUI() {
            const telefono = inputPhoneNumber.value.trim();
            if (!telefono) return;

            try {
                const response = await fetch(`/api/session/${telefono}`);
                if (response.ok) {
                    const slots = await response.json();
                    
                    // Función interna para actualizar el contenido de forma segura con textContent
                    const renderSlot = (elemento, valor) => {
                        elemento.textContent = valor;
                        if (valor === 'VACIO' || valor === '0' || valor === 0) {
                            elemento.className = 'slot-value slot-empty';
                        } else {
                            elemento.className = 'slot-value slot-filled';
                        }
                    };

                    renderSlot(slotFecha, slots.Sesion_FechaISO);
                    renderSlot(slotAmbiente, slots.Sesion_Ambiente);
                    renderSlot(slotInvitados, slots.Sesion_Invitados);
                    renderSlot(slotDispo, slots.Sesion_Disponibilidad_Fecha);
                    renderSlot(slotFallas, slots.Sesion_Sin_Categoria);
                }
            } catch (e) {
                console.error("Error al actualizar slots:", e);
            }
        }

        // Agregar mensaje en la UI de forma segura para prevenir XSS
        function agregarMensajeUI(rol, texto) {
            const wrapper = document.createElement('div');
            wrapper.className = `msg-bubble-wrapper ${rol}`;

            const bubble = document.createElement('div');
            bubble.className = 'msg-bubble';
            bubble.textContent = texto; // Protege contra inyecciones XSS

            const meta = document.createElement('div');
            meta.className = 'msg-meta';
            meta.textContent = rol === 'user' ? 'Tú' : 'Teffy';

            bubble.appendChild(meta);
            wrapper.appendChild(bubble);
            chatHistory.appendChild(wrapper);

            // Auto-scroll al final
            chatHistory.scrollTop = chatHistory.scrollHeight;
        }

        // Mostrar indicador de escritura
        function mostrarCargando() {
            const wrapper = document.createElement('div');
            wrapper.className = 'msg-bubble-wrapper bot';
            wrapper.id = 'loadingBubble';

            const bubble = document.createElement('div');
            bubble.className = 'msg-bubble';

            const indicator = document.createElement('div');
            indicator.className = 'typing-indicator';
            
            for (let i = 0; i < 3; i++) {
                const dot = document.createElement('div');
                dot.className = 'typing-dot';
                indicator.appendChild(dot);
            }

            bubble.appendChild(indicator);
            wrapper.appendChild(bubble);
            chatHistory.appendChild(wrapper);
            chatHistory.scrollTop = chatHistory.scrollHeight;
        }

        // Eliminar indicador de escritura
        function quitarCargando() {
            const loading = document.getElementById('loadingBubble');
            if (loading) {
                loading.remove();
            }
        }

        // Enviar mensaje
        chatForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const mensaje = msgInput.value.trim();
            const telefono = inputPhoneNumber.value.trim();
            if (!mensaje || !telefono) return;

            // Limpiar input
            msgInput.value = '';

            // Mostrar mensaje del usuario en pantalla
            agregarMensajeUI('user', mensaje);

            // Mostrar "escribiendo..."
            mostrarCargando();

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        phone_number: telefono,
                        message: mensaje,
                        display_phone_number: "Teffy"
                    })
                });

                quitarCargando();

                if (response.ok) {
                    const data = await response.json();
                    agregarMensajeUI('bot', data.response);
                } else {
                    agregarMensajeUI('bot', "Error de conexión con el backend.");
                }
            } catch (e) {
                quitarCargando();
                agregarMensajeUI('bot', "Error en el simulador.");
            }

            // Actualizar panel de slots tras el mensaje
            await actualizarSlotsUI();
        });

        // Restablecer sesión
        btnReset.addEventListener('click', async () => {
            const telefono = inputPhoneNumber.value.trim();
            if (!telefono) return;

            try {
                const response = await fetch(`/api/session/${telefono}/clear`, { method: 'POST' });
                if (response.ok) {
                    chatHistory.innerHTML = '';
                    agregarMensajeUI('bot', "Sesión y registros de base de datos eliminados. Estado inicializado.");
                    await actualizarSlotsUI();
                }
            } catch (e) {
                console.error(e);
            }
        });

        // Refrescar slots manualmente
        btnRefresh.addEventListener('click', actualizarSlotsUI);

        // Config & Diagnostics Modal Elements
        const btnConfig = document.getElementById('btnConfig');
        const configModal = document.getElementById('configModal');
        const closeModal = document.getElementById('closeModal');
        const btnRunDiagnostics = document.getElementById('btnRunDiagnostics');
        const diagnosticResults = document.getElementById('diagnosticResults');
        const configForm = document.getElementById('configForm');

        // Open Modal
        btnConfig.addEventListener('click', async () => {
            configModal.style.display = 'block';
            await cargarCredencialesUI();
        });

        // Close Modal
        closeModal.addEventListener('click', () => {
            configModal.style.display = 'none';
        });

        window.addEventListener('click', (e) => {
            if (e.target === configModal) {
                configModal.style.display = 'none';
            }
        });

        // Mostrar notificaciones premium personalizadas en Ventana Modal (UX/UI/CX premium)
        function mostrarAlertaUX(titulo, mensaje, tipo = 'success') {
            document.getElementById('customAlertIcon').textContent = tipo === 'success' ? '🎉' : '❌';
            document.getElementById('customAlertTitle').textContent = titulo;
            document.getElementById('customAlertMessage').textContent = mensaje;
            
            const modal = document.getElementById('customAlertModal');
            modal.style.display = 'flex';
            modal.style.alignItems = 'center';
            modal.style.justifyContent = 'center';
            
            const content = modal.querySelector('.custom-alert-content');
            content.style.transform = 'scale(0.8)';
            content.style.opacity = '0';
            setTimeout(() => {
                content.style.transition = 'all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)';
                content.style.transform = 'scale(1)';
                content.style.opacity = '1';
            }, 10);
        }

        document.getElementById('btnCustomAlertClose').addEventListener('click', () => {
            const modal = document.getElementById('customAlertModal');
            const content = modal.querySelector('.custom-alert-content');
            content.style.transform = 'scale(0.8)';
            content.style.opacity = '0';
            setTimeout(() => {
                modal.style.display = 'none';
            }, 200);
        });

        // Load Credentials to UI Form
        async function cargarCredencialesUI() {
            try {
                const response = await fetch('/api/config/credentials');
                if (response.ok) {
                    const data = await response.json();
                    document.getElementById('dbUser').value = data.DB_USER || '';
                    document.getElementById('dbPass').value = data.DB_PASSWORD || '';
                    document.getElementById('dbHost').value = data.DB_HOST || '';
                    document.getElementById('dbPort').value = data.DB_PORT || 5432;
                    document.getElementById('dbNameHv').value = data.DB_NAME_HV || '';
                    document.getElementById('dbNameRag').value = data.DB_NAME_RAG || '';
                    document.getElementById('dbNameWebhook').value = data.DB_NAME_WEBHOOK || '';
                    document.getElementById('dbNameN8n').value = data.DB_NAME_N8N || '';
                    
                    // Cargar específicos opcionales
                    document.getElementById('dbHvUser').value = data.DB_HV_USER || '';
                    document.getElementById('dbHvPass').value = data.DB_HV_PASSWORD || '';
                    document.getElementById('dbHvHost').value = data.DB_HV_HOST || '';
                    document.getElementById('dbHvPort').value = data.DB_HV_PORT || '';

                    document.getElementById('dbRagUser').value = data.DB_RAG_USER || '';
                    document.getElementById('dbRagPass').value = data.DB_RAG_PASSWORD || '';
                    document.getElementById('dbRagHost').value = data.DB_RAG_HOST || '';
                    document.getElementById('dbRagPort').value = data.DB_RAG_PORT || '';

                    document.getElementById('dbWebhookUser').value = data.DB_WEBHOOK_USER || '';
                    document.getElementById('dbWebhookPass').value = data.DB_WEBHOOK_PASSWORD || '';
                    document.getElementById('dbWebhookHost').value = data.DB_WEBHOOK_HOST || '';
                    document.getElementById('dbWebhookPort').value = data.DB_WEBHOOK_PORT || '';

                    document.getElementById('dbN8nUser').value = data.DB_N8N_USER || '';
                    document.getElementById('dbN8nPass').value = data.DB_N8N_PASSWORD || '';
                    document.getElementById('dbN8nHost').value = data.DB_N8N_HOST || '';
                    document.getElementById('dbN8nPort').value = data.DB_N8N_PORT || '';

                    document.getElementById('metaVerifyToken').value = data.META_VERIFY_TOKEN || '';
                    document.getElementById('metaAccessToken').value = data.META_ACCESS_TOKEN || '';
                    document.getElementById('metaPhoneId').value = data.META_PHONE_NUMBER_ID || '';
                    document.getElementById('openaiKey').value = data.OPENAI_API_KEY || '';
                    document.getElementById('calendarId').value = data.GOOGLE_CALENDAR_ID || '';
                    document.getElementById('calendarJson').value = data.GOOGLE_CREDENTIALS_JSON || '';
                }
            } catch (e) {
                console.error("Error al cargar credenciales:", e);
            }
        }

        // Save Credentials Form
        configForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btnSave = configForm.querySelector('button[type="submit"]');
            const originalText = btnSave.textContent;
            btnSave.textContent = 'Guardando...';
            btnSave.disabled = true;

            const payload = {
                DB_USER: document.getElementById('dbUser').value.trim(),
                DB_PASSWORD: document.getElementById('dbPass').value.trim(),
                DB_HOST: document.getElementById('dbHost').value.trim(),
                DB_PORT: parseInt(document.getElementById('dbPort').value.trim(), 10) || 5432,
                DB_NAME_HV: document.getElementById('dbNameHv').value.trim(),
                DB_NAME_RAG: document.getElementById('dbNameRag').value.trim(),
                DB_NAME_WEBHOOK: document.getElementById('dbNameWebhook').value.trim(),
                DB_NAME_N8N: document.getElementById('dbNameN8n').value.trim(),
                
                // Parámetros específicos opcionales
                DB_HV_USER: document.getElementById('dbHvUser').value.trim() || null,
                DB_HV_PASSWORD: document.getElementById('dbHvPass').value.trim() || null,
                DB_HV_HOST: document.getElementById('dbHvHost').value.trim() || null,
                DB_HV_PORT: document.getElementById('dbHvPort').value.trim() ? parseInt(document.getElementById('dbHvPort').value.trim(), 10) : null,

                DB_RAG_USER: document.getElementById('dbRagUser').value.trim() || null,
                DB_RAG_PASSWORD: document.getElementById('dbRagPass').value.trim() || null,
                DB_RAG_HOST: document.getElementById('dbRagHost').value.trim() || null,
                DB_RAG_PORT: document.getElementById('dbRagPort').value.trim() ? parseInt(document.getElementById('dbRagPort').value.trim(), 10) : null,

                DB_WEBHOOK_USER: document.getElementById('dbWebhookUser').value.trim() || null,
                DB_WEBHOOK_PASSWORD: document.getElementById('dbWebhookPass').value.trim() || null,
                DB_WEBHOOK_HOST: document.getElementById('dbWebhookHost').value.trim() || null,
                DB_WEBHOOK_PORT: document.getElementById('dbWebhookPort').value.trim() ? parseInt(document.getElementById('dbWebhookPort').value.trim(), 10) : null,

                DB_N8N_USER: document.getElementById('dbN8nUser').value.trim() || null,
                DB_N8N_PASSWORD: document.getElementById('dbN8nPass').value.trim() || null,
                DB_N8N_HOST: document.getElementById('dbN8nHost').value.trim() || null,
                DB_N8N_PORT: document.getElementById('dbN8nPort').value.trim() ? parseInt(document.getElementById('dbN8nPort').value.trim(), 10) : null,

                META_VERIFY_TOKEN: document.getElementById('metaVerifyToken').value.trim(),
                META_ACCESS_TOKEN: document.getElementById('metaAccessToken').value.trim(),
                META_PHONE_NUMBER_ID: document.getElementById('metaPhoneId').value.trim(),
                OPENAI_API_KEY: document.getElementById('openaiKey').value.trim(),
                GOOGLE_CALENDAR_ID: document.getElementById('calendarId').value.trim(),
                GOOGLE_CREDENTIALS_JSON: document.getElementById('calendarJson').value.trim()
            };

            try {
                const response = await fetch('/api/config/credentials', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const resData = await response.json();
                if (response.ok) {
                    mostrarAlertaUX('¡Guardado Exitoso!', 'La configuración se guardó y aplicó correctamente en caliente.', 'success');
                } else {
                    mostrarAlertaUX('Error de Guardado', resData.detail || 'No se pudieron aplicar los cambios.', 'error');
                }
            } catch (err) {
                console.error("Error al guardar credenciales:", err);
                mostrarAlertaUX('Error de Red', 'No se pudo comunicar con el servidor para guardar.', 'error');
            } finally {
                btnSave.textContent = originalText;
                btnSave.disabled = false;
            }
        });

        // Toggle visibility for passwords
        document.querySelectorAll('.toggle-password').forEach(btn => {
            btn.addEventListener('click', () => {
                const targetId = btn.getAttribute('data-target');
                const input = document.getElementById(targetId);
                if (input.type === 'password') {
                    input.type = 'text';
                    btn.textContent = '🔒';
                } else {
                    input.type = 'password';
                    btn.textContent = '👁️';
                }
            });
        });

        // Run Individual Diagnostics
        async function probarConexionIndividual(servicio) {
            const statusBadge = document.getElementById(`status-${servicio}`);
            const errorMsg = document.getElementById(`error-${servicio}`);
            const btn = document.querySelector(`.btn-test-service[data-service="${servicio}"]`);
            const btnSave = document.querySelector(`.btn-save-service[data-service="${servicio}"]`);
            
            if (btn) btn.disabled = true;
            if (btnSave) btnSave.style.display = 'none';
            statusBadge.className = 'status-badge pending';
            statusBadge.textContent = 'Probando...';
            errorMsg.textContent = 'Conectando al servicio...';
            errorMsg.style.color = 'var(--text-muted)';

            const payload = {
                DB_USER: document.getElementById('dbUser').value.trim(),
                DB_PASSWORD: document.getElementById('dbPass').value.trim(),
                DB_HOST: document.getElementById('dbHost').value.trim(),
                DB_PORT: parseInt(document.getElementById('dbPort').value.trim(), 10) || 5432,
                DB_NAME_HV: document.getElementById('dbNameHv').value.trim(),
                DB_NAME_RAG: document.getElementById('dbNameRag').value.trim(),
                DB_NAME_WEBHOOK: document.getElementById('dbNameWebhook').value.trim(),
                DB_NAME_N8N: document.getElementById('dbNameN8n').value.trim(),
                
                // Específicos opcionales
                DB_HV_USER: document.getElementById('dbHvUser').value.trim() || null,
                DB_HV_PASSWORD: document.getElementById('dbHvPass').value.trim() || null,
                DB_HV_HOST: document.getElementById('dbHvHost').value.trim() || null,
                DB_HV_PORT: document.getElementById('dbHvPort').value.trim() ? parseInt(document.getElementById('dbHvPort').value.trim(), 10) : null,

                DB_RAG_USER: document.getElementById('dbRagUser').value.trim() || null,
                DB_RAG_PASSWORD: document.getElementById('dbRagPass').value.trim() || null,
                DB_RAG_HOST: document.getElementById('dbRagHost').value.trim() || null,
                DB_RAG_PORT: document.getElementById('dbRagPort').value.trim() ? parseInt(document.getElementById('dbRagPort').value.trim(), 10) : null,

                DB_WEBHOOK_USER: document.getElementById('dbWebhookUser').value.trim() || null,
                DB_WEBHOOK_PASSWORD: document.getElementById('dbWebhookPass').value.trim() || null,
                DB_WEBHOOK_HOST: document.getElementById('dbWebhookHost').value.trim() || null,
                DB_WEBHOOK_PORT: document.getElementById('dbWebhookPort').value.trim() ? parseInt(document.getElementById('dbWebhookPort').value.trim(), 10) : null,

                DB_N8N_USER: document.getElementById('dbN8nUser').value.trim() || null,
                DB_N8N_PASSWORD: document.getElementById('dbN8nPass').value.trim() || null,
                DB_N8N_HOST: document.getElementById('dbN8nHost').value.trim() || null,
                DB_N8N_PORT: document.getElementById('dbN8nPort').value.trim() ? parseInt(document.getElementById('dbN8nPort').value.trim(), 10) : null,

                META_VERIFY_TOKEN: document.getElementById('metaVerifyToken').value.trim(),
                META_ACCESS_TOKEN: document.getElementById('metaAccessToken').value.trim(),
                META_PHONE_NUMBER_ID: document.getElementById('metaPhoneId').value.trim(),
                OPENAI_API_KEY: document.getElementById('openaiKey').value.trim(),
                GOOGLE_CALENDAR_ID: document.getElementById('calendarId').value.trim(),
                GOOGLE_CREDENTIALS_JSON: document.getElementById('calendarJson').value.trim()
            };
            
            try {
                const response = await fetch(`/api/diagnostics/test/${servicio}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (response.ok) {
                    const data = await response.json();
                    if (data.status === 'ok') {
                        statusBadge.className = 'status-badge ok';
                        statusBadge.textContent = 'Exitosa';
                        errorMsg.textContent = data.message;
                        errorMsg.style.color = '#10b981';
                        if (btnSave) btnSave.style.display = 'inline-block';
                    } else {
                        statusBadge.className = 'status-badge error';
                        statusBadge.textContent = 'Error';
                        errorMsg.textContent = data.message;
                        errorMsg.style.color = '#ef4444';
                    }
                } else {
                    statusBadge.className = 'status-badge error';
                    statusBadge.textContent = 'Error';
                    errorMsg.textContent = 'Error de servidor al validar la conexión.';
                    errorMsg.style.color = '#ef4444';
                }
            } catch (err) {
                statusBadge.className = 'status-badge error';
                statusBadge.textContent = 'Error';
                errorMsg.textContent = 'Error de red: ' + err.message;
                errorMsg.style.color = '#ef4444';
            } finally {
                if (btn) btn.disabled = false;
            }
        }

        // Hook Individual buttons
        document.querySelectorAll('.btn-test-service').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault(); // Evitar submit accidental del form
                const service = btn.getAttribute('data-service');
                probarConexionIndividual(service);
            });
        });

        // Hook Individual Save buttons
        document.querySelectorAll('.btn-save-service').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                configForm.requestSubmit(); // Dispara la validación y el submit del formulario
            });
        });

        // Run All Diagnostics (Probar Todo)
        btnRunDiagnostics.addEventListener('click', async (e) => {
            e.preventDefault();
            btnRunDiagnostics.disabled = true;
            btnRunDiagnostics.textContent = 'Probando...';
            const services = ['db_server', 'db_hv', 'db_rag', 'db_webhook', 'db_n8n', 'openai', 'whatsapp', 'google_calendar'];
            for (const service of services) {
                await probarConexionIndividual(service);
            }
            btnRunDiagnostics.textContent = '🧪 Probar Todo';
            btnRunDiagnostics.disabled = false;
        });

        // Inicializar slots en carga
        actualizarSlotsUI();
    