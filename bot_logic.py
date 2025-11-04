from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from models import Gasto # Importa o modelo de tabela
from datetime import datetime, timedelta
import re

# --- LÓGICA DE LIMPEZA ---
def limpar_gastos_antigos(db: Session):
    dias_para_manter = 180
    data_limite = datetime.now() - timedelta(days=dias_para_manter)
    num_deletados = db.query(Gasto).filter(
        Gasto.data_criacao < data_limite
    ).delete(synchronize_session=False)
    db.commit()
    print(f"🗑️ Limpeza executada. {num_deletados} gastos anteriores a {data_limite.strftime('%Y-%m-%d')} foram apagados.")
    return num_deletados

# --- FUNÇÃO PRINCIPAL DE PROCESSAMENTO ---
def processar_mensagem(db: Session, user_id: int, texto: str, nome_usuario: str):
    
    resposta = ""
    parse_mode = "HTML"
    aviso_aspas = ""

    texto_lower = texto.lower().strip()
    comando_limpo = texto_lower
    if texto_lower.startswith('/'):
        comando_limpo = texto_lower[1:]

    # --- LÓGICA DO /START ---
    if comando_limpo == "start":
        resposta = f"Olá, <b>{nome_usuario}</b>! 👋\n\n"
        resposta += "<b>Como anotar um gasto:</b>\n"
        resposta += "<code>15.50 padaria</code>\n"
        resposta += "<code>100 \"lava louça\"</code>\n"
        resposta += "<code>120 \"supermercado\" compra do mês</code>\n\n"
        resposta += "<b>Comandos disponíveis:</b>\n"
        resposta += "<code>/listar</code> | <code>/relatorio</code> | <code>/deletar [IDs]</code> | <code>/zerartudo</code>\n\n"
        resposta += "ℹ️ <i>Gastos com mais de 6 meses são removidos automaticamente.</i>"

    # --- LÓGICA DO /RELATORIO ---
    elif comando_limpo == "relatorio":
        consulta = db.query(
            Gasto.categoria, func.sum(Gasto.valor)
        ).filter(Gasto.user_id == user_id).group_by(Gasto.categoria).all()
        total_geral = 0
        resposta = "📊 <b>Seu Relatório por Categoria</b> 📊\n\n"
        if not consulta:
            resposta += "Nenhum gasto registrado ainda."
        else:
            for categoria, total in consulta:
                resposta += f"<b>{categoria.capitalize()}:</b> R$ {total:.2f}\n"
                total_geral += total
            resposta += f"\n──────────\n<b>SEU TOTAL: R$ {total_geral:.2f}</b>"

    # --- LÓGICA DO /LISTAR ---
    elif comando_limpo == "listar":
        parse_mode = None # Desliga HTML para este comando
        consulta = db.query(Gasto).filter(Gasto.user_id == user_id).order_by(Gasto.id_local_usuario.desc()).limit(5).all()
        resposta = "📋 Seus Últimos 5 Gastos 📋\n\n"
        if not consulta:
            resposta += "Nenhum gasto registrado ainda."
        else:
            for gasto in consulta:
                try:
                    data_formatada = "Sem Data"
                    if gasto.data_criacao:
                        data_formatada = gasto.data_criacao.strftime('%d/%m %H:%M')
                    linha = f"ID {gasto.id_local_usuario}: R$ {gasto.valor:.2f} ({gasto.categoria})"
                    if gasto.descricao:
                        linha += f" - {gasto.descricao}"
                    linha += f" [{data_formatada}]\n"
                    resposta += linha
                except Exception as e:
                    print(f"⚠️ Erro ao formatar Gasto ID {gasto.id}: {e}")
                    resposta += f"⚠️ Erro ao exibir Gasto ID {gasto.id}\n"
        resposta += "\n(Mostrando os últimos 5)"

    # --- LÓGICA DO /DELETAR (COM VÍRGULA) ---
    elif comando_limpo.startswith("deletar"):
        try:
            partes = comando_limpo.split(maxsplit=1) 
            if len(partes) != 2 or not partes[1]:
                raise ValueError("Formato incorreto, faltou o(s) ID(s)")
            ids_string = partes[1]
            ids_para_deletar_str = [id_str.strip() for id_str in ids_string.split(',')]
            if not ids_para_deletar_str or all(s == '' for s in ids_para_deletar_str):
                raise ValueError("Formato incorreto, nenhum ID fornecido.")
            
            ids_deletados_sucesso = []
            ids_falhados = []
            
            for id_str in ids_para_deletar_str:
                if not id_str: continue 
                try:
                    id_local = int(id_str)
                    gasto = db.query(Gasto).filter(
                        Gasto.id_local_usuario == id_local, 
                        Gasto.user_id == user_id
                    ).first()
                    if gasto:
                        db.delete(gasto)
                        ids_deletados_sucesso.append(id_str)
                    else:
                        ids_falhados.append(id_str)
                except ValueError:
                    ids_falhados.append(id_str)
            
            if ids_deletados_sucesso:
                db.commit()

            resposta = ""
            if ids_deletados_sucesso:
                ids_str = ", ".join(ids_deletados_sucesso)
                resposta += f"✅ Gastos com IDs locais <b>{ids_str}</b> foram deletados.\n"
            if ids_falhados:
                ids_str = ", ".join(ids_falhados)
                resposta += f"❌ Os seguintes IDs/palavras não foram encontrados ou são inválidos: <b>{ids_str}</b>."
            if not resposta:
                resposta = "❌ Nenhum ID válido foi processado."
        except (IndexError, ValueError) as e:
            print(f"ERRO no /deletar: {e}")
            resposta = "❌ Uso: <code>/deletar [ID1],[ID2]...</code> (separados por vírgula)."

    # --- LÓGICA DO /ZERARTUDO ---
    elif comando_limpo.startswith("zerartudo"):
        partes = comando_limpo.split()
        if len(partes) == 2 and partes[1] == "confirmar":
            num_deletados = db.query(Gasto).filter(Gasto.user_id == user_id).delete()
            db.commit()
            resposta = f"🔥 Todos os seus <b>{num_deletados}</b> gastos foram apagados!"
        else:
            resposta = "⚠️ <b>Atenção!</b> Apagará TODOS os SEUS gastos.\nEnvie <code>/zerartudo confirmar</code>"

    # --- LÓGICA DE SALVAR NOVO GASTO ---
    else:
        try:
            texto_corrigido = texto.replace("“", "\"").replace("”", "\"")
            partes_por_aspas = texto_corrigido.split('"')
            aviso_aspas = False

            if len(partes_por_aspas) == 3:
                valor_str = partes_por_aspas[0].strip().replace(',', '.')
                valor_float = float(valor_str)
                categoria = partes_por_aspas[1].strip()
                descricao = partes_por_aspas[2].strip() or None
            else:
                partes = texto.split()
                if len(partes) < 2: raise ValueError("Faltou valor ou categoria")
                valor_str = partes[0].replace(",", ".")
                valor_float = float(valor_str)
                categoria = partes[1]
                if len(partes) > 2:
                    descricao = " ".join(partes[2:])
                    aviso_aspas = True
                else:
                    descricao = None
                    if len(partes) > 1 :
                        aviso_aspas = True

            if not categoria: raise ValueError("Categoria vazia")

            ultimo_id_local_obj = db.query(func.max(Gasto.id_local_usuario)).filter(Gasto.user_id == user_id).scalar()
            novo_id_local = 1
            if ultimo_id_local_obj is not None:
                novo_id_local = ultimo_id_local_obj + 1
            
            novo_gasto = Gasto(
                user_id=user_id,
                id_local_usuario=novo_id_local,
                valor=valor_float,
                categoria=categoria.lower(),
                descricao=descricao
            )
            db.add(novo_gasto)
            db.commit()
            db.refresh(novo_gasto)

            resposta = f"✅ Gasto salvo!\n<b>ID: {novo_id_local}</b>\n<b>Valor:</b> R$ {valor_float:.2f}\n<b>Categoria:</b> {categoria.lower()}"
            
            if aviso_aspas and resposta.startswith("✅"):
                 aviso_aspas = (f"⚠️ Categoria '{categoria}' salva como palavra única.\n"
                          "Use aspas para múltiplas palavras: <code>VALOR \"CATEGORIA LONGA\"</code>")
        
        except (ValueError, IndexError):
            resposta = "❌ Formato inválido. Use <code>VALOR CATEGORIA</code> ou <code>/start</code>."

    # Retorna os três resultados
    return (resposta, parse_mode, aviso_aspas)
