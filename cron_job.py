# cron_job.py (Atualizado para a nova estrutura)
import os
import sys
from sqlalchemy.orm import Session
from database import SessionLocal, Base, engine # <<< Importa do novo arquivo
from bot_logic import limpar_gastos_antigos # <<< Importa do novo arquivo

# Configuração de Logs
print("--- INICIANDO CRON JOB DE LIMPEZA ---")

# Garante que as tabelas estão prontas antes de iniciar
try:
    Base.metadata.create_all(bind=engine)
    print("Sucesso: Tabelas verificadas/criadas.")
except Exception as e:
    print(f"ERRO CRÍTICO DURANTE CRIAÇÃO DAS TABELAS: {e}")
    sys.exit(1) # Sai se o banco falhar

# Inicia a sessão e executa a limpeza
db: Session = SessionLocal()
try:
    num_limpos = limpar_gastos_antigos(db)
    print(f"✅ CRON JOB CONCLUÍDO. Total de {num_limpos} registros deletados.")
except Exception as e:
    print(f"❌ ERRO CRÍTICO DURANTE O CRON JOB: {e}")
finally:
    db.close()

print("--- FIM DO CRON JOB ---")
