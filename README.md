# Nova Info — base multi-tenant

Fundação inicial do SaaS Nova Info, com identificação de estabelecimentos por
subdomínio e acesso ao painel condicionado a uma associação ativa do usuário.

## Desenvolvimento local

```sh
/usr/bin/python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Para testar um estabelecimento local, use um host como
`restaurante-a.localhost:8000` (ou `restaurante-a.novainfo.com.br` apontado para
o servidor local). Crie o estabelecimento e associe usuários pelo Django Admin.

O domínio raiz não seleciona tenant; um tenant é resolvido somente por um
subdomínio direto de `TENANT_ROOT_DOMAIN`. Subdomínios inexistentes e tenants
inativos retornam 404. O painel também retorna 404 para usuários sem associação
ativa, evitando revelar quais estabelecimentos existem.

## Banco de dados

SQLite é usado por padrão no desenvolvimento. Para PostgreSQL, instale as
dependências e configure `DB_ENGINE=postgres`, `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `DB_HOST` e `DB_PORT`.

Em produção, defina `DJANGO_DEBUG=false`, `DJANGO_SECRET_KEY` e
`DJANGO_ALLOWED_HOSTS`; HTTPS e cookies seguros são exigidos pelas configurações.

## Escopo implementado

- Modelo de estabelecimento com slug de subdomínio validado e nomes reservados.
- Associação única usuário/estabelecimento com papéis iniciais.
- Middleware que resolve o tenant a partir do host validado pelo Django.
- Proteção do painel por associação ativa, com resposta não reveladora para
  usuários não autorizados.
- Modelo-base `TenantOwnedModel` para associar os próximos registros ao tenant,
  com consulta explícita via `.objects.for_tenant(tenant)`.
- Testes de resolução e isolamento entre estabelecimentos.

As integrações MikroTik, WireGuard, RADIUS, cobrança e portal cativo ainda não
estão implementadas; não são simuladas nesta base.

## Site institucional

A página pública está disponível na rota `/` e apresenta o escopo planejado da
plataforma sem afirmar que integrações futuras já estão ativas. O formulário
`/demonstracao/` registra solicitações de contato e inclui proteção CSRF,
validação de campos e um campo honeypot básico contra spam. As solicitações
podem ser consultadas por administradores em `/admin/`, no modelo
"Solicitações de demonstração". O visitante é informado de que os dados enviados
serão usados para responder ao pedido.
