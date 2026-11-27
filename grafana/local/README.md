# Configuração do MySQL para os painéis do cliente e do admin

O Grafana local usa DuckDB no `Painel Cliente Técnico` e MySQL em `Painel do Cliente` e `Painel do Admin`. A fonte `MySQL-Escola` está em `provisioning/datasources/mysql-escola.yml` e aponta para:

| Parâmetro | Valor |
|---|---|
| Host/porta | `172.17.0.1:3306` (no Linux, o gateway do Docker) |
| Banco | `boost` |
| Usuário | `grafana` |
| Senha | `grafana_password` |
| UID no Grafana | `mysql-escola-uid` |

Em Docker Desktop (Windows/macOS), troque a URL do YAML para `host.docker.internal:3306`. Se alterar usuário, senha ou banco, altere também o YAML e reinicie o Grafana.

## 1. Liberar a porta e o bind do MySQL

No host onde o MySQL roda, confirme que ele está escutando na porta 3306:

```bash
sudo ss -ltnp | grep 3306
```

Se a porta não aparecer, inicie o serviço:

```bash
sudo systemctl enable --now mysql
```

Se o MySQL estiver preso apenas em `127.0.0.1`, edite `/etc/mysql/mysql.conf.d/mysqld.cnf` (Ubuntu/Debian) e ajuste:

```ini
bind-address = 0.0.0.0
```

Depois reinicie:

```bash
sudo systemctl restart mysql
```

Libere o tráfego do Docker no firewall. Com UFW:

```bash
sudo ufw allow from 172.17.0.0/16 to any port 3306 proto tcp
```

Com firewalld:

```bash
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="172.17.0.0/16" port port="3306" protocol="tcp" accept'
sudo firewall-cmd --reload
```

No Windows, libere a porta TCP 3306 no Firewall do Windows para as redes do Docker Desktop.

## 2. Criar banco, usuário e permissão

Entre no MySQL como root:

```bash
sudo mysql -u root -p
```

Rode:

```sql
CREATE DATABASE IF NOT EXISTS boost CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'grafana'@'%' IDENTIFIED BY 'grafana_password';
GRANT SELECT ON boost.* TO 'grafana'@'%';

FLUSH PRIVILEGES;
```

Se preferir restringir o acesso apenas à rede do Docker, use `'grafana'@'172.17.0.%'` no lugar de `'grafana'@'%'` nos dois comandos.

Se aparecer erro de autenticação com `caching_sha2_password`, rode também:

```sql
ALTER USER 'grafana'@'%' IDENTIFIED WITH mysql_native_password BY 'grafana_password';
FLUSH PRIVILEGES;
```

## 3. Conferir as tabelas

Os painéis só leem. O banco `boost` precisa conter as tabelas usadas nas consultas:

```text
aluno
contrato
disponibilidade_aluno
disponibilidade_professor
horario
logs
permissao
professor
professor_permissao
turma
```

Se faltar alguma, importe o dump/seed da aplicação antes de abrir os painéis.

## 4. Testar e aplicar

Teste a conexão a partir do host:

```bash
mysql -h 127.0.0.1 -P 3306 -u grafana -p boost
```

Reinicie o Grafana para recarregar o provisioning:

```bash
cd grafana/local
docker compose restart grafana
```

Abra `http://localhost:3000`, vá em **Connections > Data sources > MySQL-Escola** e clique em **Save & test**. Depois abra `Painel do Cliente` e `Painel do Admin`.

## 5. Problemas comuns

| Sintoma | Causa provável | Verificação |
|---|---|---|
| `connection refused` | MySQL parado, porta fechada ou bind errado | `sudo ss -ltnp \| grep 3306` |
| `access denied for user 'grafana'` | usuário/senha ou host errados | refaça o passo 2 |
| `unknown database 'boost'` | banco não criado | `SHOW DATABASES;` |
| `table doesn't exist` | dump/seed não importado | `SHOW TABLES;` no banco `boost` |
| Painel vazio, sem erro | tabelas sem dados ou filtro de tempo | `SELECT COUNT(*) FROM contrato;` |
| `Data source not found` | YAML não carregado | reinicie o container e repita o Save & test |

A senha acima é apenas para uso local. Não reutilize ela em ambiente de produção.
