# --- NOSSO ENDPOINT DE WEBHOOK (TESTE DE LOGS EXTREMOS) ---
@app.post("/webhook")
async def webhook(update: Update, db: Session = Depends(get_db)): # << MUDANÇA ESSENCIAL
    chat_id = update.message.chat.id
    texto = update.message.text
    nome_usuario = update.message.from_user.first_name

    print(f"--- MENSAGEM RECEBIDA (Chat ID: {chat_id}) ---")
    print(f"De: {nome_usuario} | Texto: {texto}")
    
    resposta = "" 
    mensagem_foi_enviada = False # Flag de controle

    # Bloco try/except principal
    try:
        if texto:
            texto_lower = texto.lower()
            comando_identificado = False # Flag para saber se entrou em algum if/elif

            # --- LÓGICA DO /START ---
            if texto_lower.strip() == "/start":
                comando_identificado = True
                print("[DEBUG] Entrou na lógica /start")
                resposta = f"Olá, <b>{nome_usuario}</b>! 👋\n\n"
                # ... (resto da mensagem do /start)
                resposta += "Para APAGAR TUDO, envie: <code>/zerartudo confirmar</code>"

            # --- LÓGICA DO /RELATORIO ---
            elif texto_lower.strip() == "/relatorio":
                comando_identificado = True
                print("[DEBUG] Entrou na lógica /relatorio")
                # ... (Código do relatorio como antes) ...
                resposta += f"<b>TOTAL GERAL: R$ {total_geral:.2f}</b>"

            # --- (LÓGICA DO /LISTAR CORRIGIDA E ESTÁVEL) ---
            elif texto_lower.strip() == "/listar":
                comando_identificado = True
                print("[DEBUG] Entrou na lógica /listar")
                consulta = db.query(Gasto).order_by(Gasto.id.desc()).limit(10).all()
                
                resposta = "📋 <b>Últimos 10 Gastos Registrados</b> 📋\n\n"
                if not consulta:
                    resposta += "Nenhum gasto registrado ainda."
                    print("[DEBUG] /listar: Nenhum gasto encontrado.")
                else:
                    print(f"[DEBUG] /listar: Encontrados {len(consulta)} gastos para listar.")
                    for i, gasto in enumerate(consulta):
                        print(f"[DEBUG] /listar: Processando item {i+1}, ID {gasto.id}")
                        try:
                            data_formatada = "Sem Data"
                            if gasto.data_criacao:
                                data_formatada = gasto.data_criacao.strftime('%d/%m/%Y %H:%M')
                            
                            resposta += f"<b>ID: {gasto.id}</b> | R$ {gasto.valor:.2f} | {gasto.categoria}\n"
                            if gasto.descricao:
                                resposta += f"   └ <i>{gasto.descricao}</i>\n"
                            resposta += f"   <small>({data_formatada})</small>\n\n"
                        except Exception as e:
                            print(f"[DEBUG] ERRO no loop do /listar, item ID {gasto.id}: {e}")
                            resposta += f"⚠️ Erro ao exibir Gasto ID {gasto.id}. Tente deletá-lo.\n\n"

            # --- LÓGICA DO /DELETAR ---
            elif texto_lower.startswith("/deletar"):
                comando_identificado = True
                print("[DEBUG] Entrou na lógica /deletar")
                # ... (Código do deletar como antes) ...
                resposta += "Use <code>/listar</code> para ver os IDs."
            
            # --- LÓGICA DO /ZERARTUDO ---
            elif texto_lower.startswith("/zerartudo"):
                comando_identificado = True
                print("[DEBUG] Entrou na lógica /zerartudo")
                # ... (Código do zerartudo como antes) ...
                resposta += "<code>/zerartudo confirmar</code>"

            # --- LÓGICA DE SALVAR GASTO (O "ELSE" FINAL) ---
            else:
                comando_identificado = True # Considera salvar como um comando válido
                print("[DEBUG] Entrou na lógica de salvar gasto")
                try:
                    # ... (Código de salvar como antes) ...
                    resposta = f"✅ Gasto salvo!\n<b>ID: {novo_gasto.id}</b>..."
                except (ValueError, IndexError):
                    resposta = "❌ Formato inválido..."

            # --- BLOCO DE ENVIO FINAL ---
            print(f"[DEBUG] Fim da lógica if/elif. Comando identificado: {comando_identificado}. Resposta gerada (tem conteúdo?): {bool(resposta)}")
            if resposta and comando_identificado: # Só envia se gerou resposta E entrou em um bloco
                print("[DEBUG] PREPARANDO PARA ENVIAR MENSAGEM...")
                await send_message(chat_id, resposta)
                mensagem_foi_enviada = True
                print("[DEBUG] CHAMADA send_message() CONCLUÍDA.")
            elif not comando_identificado:
                 print("[DEBUG] Comando não reconhecido, NENHUMA resposta será enviada.")
                 # Opcional: enviar uma mensagem de comando inválido
                 # await send_message(chat_id, "Comando não reconhecido. Envie /start para ajuda.")
                 # mensagem_foi_enviada = True 
            else:
                print("[DEBUG] Resposta estava vazia, NENHUMA mensagem será enviada.")
            # --- FIM DO BLOCO DE ENVIO ---

    except Exception as e:
        print(f"ERRO FATAL NA FUNÇÃO WEBHOOK: {e}")
        try:
            await send_message(chat_id, "❌ Desculpe, ocorreu um erro fatal no servidor.")
            mensagem_foi_enviada = True # Mesmo erro fatal, tentamos enviar
        except:
            print("Falha até ao enviar mensagem de erro fatal.")

    print(f"[DEBUG] Webhook finalizado. Mensagem foi enviada: {mensagem_foi_enviada}")
    print("--------------------------------------------------")
    return {"status": "ok"}
