"""
Execute este script para gerar o hash da senha de administrador.
Uso: python generate_hash.py
Depois copie o hash gerado para a variável ADMIN_PASSWORD_HASH no .env
"""
import bcrypt

senha = input("Digite a senha do tesoureiro: ").strip()
if not senha:
    print("Senha não pode ser vazia.")
    exit(1)

hashed = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt(12))
print("\n✅ Hash gerado com sucesso!\n")
print("Adicione ao seu .env ou nas variáveis de ambiente do Render:")
print(f"\nADMIN_PASSWORD_HASH={hashed.decode('utf-8')}\n")
