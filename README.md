# Nova Info — site comercial e central multi-tenant

Site público e gestão de estabelecimentos em Django 5.2. As funcionalidades de
cadastro não pressupõem que exista conectividade ativa. Equipamentos sem
integração aparecem como **Aguardando configuração**.

## Desenvolvimento

```sh
. myenv/bin/activate
DB_USER=marcos python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 8001
```

A central está em `/central/`, com login em `/central/login/`. Exige usuário
ativo, staff e a permissão `operations.manage_network` (superusers já a possuem).
Não há senha administrativa padrão. A permissão permite consultar e administrar
os estabelecimentos; não a atribua a clientes.

O botão **ACESSAR MINHA CONTA** abre `/minha-conta/` e direciona ao subdomínio
informado. Crie estabelecimentos e associações na central; contas Django podem
ser criadas pelo Admin. Owner/admin editam seus cadastros e consultam logs;
staff/viewer consultam dados comerciais, sem edição nem logs pessoais.
Para testar `hotel.localhost:8001`, use `TENANT_ROOT_DOMAIN=localhost` e crie
um estabelecimento com slug `hotel`. Domínios reais exigem DNS wildcard e TLS.

O desenvolvimento pode usar o PostgreSQL local indicado em `.local/database.json`.
Esse descritor só é carregado com DEBUG=true; variáveis DB_* têm prioridade.
O socket, os arquivos do cluster, backups e a chave local ficam em `.local/`,
fora do Git e com acesso restrito ao usuário do sistema. Para iniciar o cluster:

```sh
/usr/lib/postgresql/16/bin/pg_ctl -D .local/postgresql -l .local/postgresql.log -o "-k $PWD/.local/pgsocket -p 55433 -h ''" start
```

Para migrations no PostgreSQL local, execute com `DB_USER=marcos`; a aplicação
usa `novainfo_app`, sem propriedade das tabelas, SUPERUSER ou BYPASSRLS.
O SQLite anterior permanece como backup; não houve migração de produção.
SQLite é suportado somente como alternativa explícita de desenvolvimento e
não oferece isolamento RLS. Produção exige PostgreSQL, migrations, HTTPS,
credencial de runtime restrita e secret key externa. Veja `.env.example`.

## Cadastros e painéis

- Central: estabelecimentos, associações, MikroTiks, WireGuard, conexões, Hotspot,
  planos de acesso, assinaturas SaaS, publicidade, vendas, pagamentos, relatórios,
  auditoria e configuração de rede/retenção.
- Tenant: equipamentos, planos/preços/períodos, dados comerciais, sessões,
  configuração de portal, logotipo/publicidade e prévia mobile privada.
- Vitrine: `/`, `/planos/`, documentos de privacidade, sitemap e robots.
  O painel comercial usa números demonstrativos claramente identificados.
- Formulário de demonstração: CSRF, validação e honeypot; os pedidos são reais.

As assinaturas Starter/Profissional/Empresarial são editáveis no Django Admin,
sem preço definitivo inicial. Planos de acesso pertencem a cada estabelecimento.
Nenhum indicador operacional é preenchido com dados fictícios.

## PostgreSQL e isolamento

As tabelas operacionais/configurações usam ENABLE e FORCE ROW LEVEL SECURITY.
USING e WITH CHECK verificam tenant, identidade, associação e estabelecimento
ativos; as políticas centrais exigem uma identidade staff autorizada e contexto
central explícito. A permissão é conferida também no banco. Um cliente não pode
obter acesso global apenas ativando a flag central.

O middleware define contexto por transação e o restaura ao final da requisição.
Workers usam `tenant_database_context` com identidade autorizada. SQL sem filtro
continua sujeito às políticas. Chaves compostas impedem relações entre tenants
em vendas/planos, pagamentos/vendas, sessões/equipamentos, peers/equipamentos,
saúde/equipamentos, histórico/equipamentos, ocorrências/equipamentos e alertas.

Os cadastros de estabelecimentos e associações também usam RLS: clientes só
consultam seu estabelecimento e associações autorizadas; alterações exigem a
permissão central. Uma função de resolução retorna somente id, nome, slug e
estado ativo para a página pública de login. Ela pertence a um papel NOLOGIN
com BYPASSRLS limitado a SELECT no cadastro, sem credenciais, contato ou VPN na
resposta. A criação desse papel requer migrator privilegiado e revisão em produção.
O runtime não pertence ao papel resolver nem pode alterar a função. Contas Django
são identidades globais, pois um usuário pode participar de vários estabelecimentos.
As tabelas de configuração e auditoria central são exclusivas da equipe.

Produção recusa SQLite, papéis SUPERUSER/BYPASSRLS, propriedade das tabelas pelo
runtime e ausência de RLS/FORCE/políticas. Use credencial separada para migrations.
O runtime precisa somente de SELECT/INSERT/UPDATE/DELETE e USAGE nas sequences;
não conceda TRUNCATE ou DDL. Administradores de banco têm privilégios próprios.

## WireGuard

Uma rede central recebe peers dos MikroTiks (RouterOS 7) ou gateways externos
(RouterOS 6). Configure endpoint, porta, interface, rede privada e chave **pública**
na central. A chave privada do servidor não é armazenada pela aplicação.

A reserva de IP usa bloqueio transacional do cadastro central e unicidade no
banco. IPs revogados não são reaproveitados automaticamente. O cadastro de peer
não ativa um túnel. No RouterOS 7, crie uma interface dedicada `ni-wg-ID`, copie
sua chave pública e cadastre-a na central; a chave privada fica no roteador.
Arquivos gerados: fragmento do servidor, modelo de gateway e script RouterOS.
O script verifica a interface/chave e interrompe se já existir configuração que
exija revisão. RouterOS 6 recebe orientação de gateway/atualização, sem comandos
WireGuard incompatíveis.

Os scripts não alteram serviços API, firewall ou infraestrutura automaticamente.
Depois da revisão, a aplicação de um peer em runtime é um comando separado:

```sh
python manage.py apply_wireguard_peer ID --reviewed
```

O comando não sobrescreve `wg0.conf`, não altera rotas de peers existentes e
recusa sobreposição de IPs. A revogação pela interface suspende o monitoramento e
marca remoção pendente; execute o comando revisado para remover o peer do kernel.
O retorno distingue remoção confirmada de pedido pendente. Atualize a configuração
persistente sob revisão para impedir que o peer retorne após um reinício.

## Monitoramento real

Configure `WG_MONITOR_USER_ID` com uma conta de serviço Django ativa/staff que
tenha `operations.manage_network`; prefira conta sem senha utilizável. Instale
wireguard-tools e conceda ao worker a capacidade estritamente necessária para ler
WireGuard. A aplicação web não deve executar como root nem receber CAP_NET_ADMIN.
`deploy/` contém modelos de service/timer para revisão, não instalados.

```sh
python manage.py monitor_network
```

Agende uma rodada a cada 60 segundos. O worker consulta somente
`latest-handshakes` e `allowed-ips`; nunca usa `wg show dump`, que pode revelar a
chave privada do servidor. Handshake recente indica apenas VPN, não API/Hotspot.
VPN não verificada impede a consulta API e gera estado desconhecido.

O adaptador binário suporta login de RouterOS 6.43+ e 7 via API-SSL, porta 8729,
com certificado confiável ou fingerprint SHA-256 confirmado. Antes do socket,
confirma que a rota do IP passa pela interface VPN configurada. O IP de gerência
deve ser o /32 reservado do peer, inclusive em topologia com gateway externo.
A API pública/WAN não é utilizada. Configure uma conta RouterOS `read,api` e
limite a origem ao IP VPN central; não exponha 8728/8729 à internet.

Os comandos permitidos são apenas consultas de recursos, servidores Hotspot e
sessões ativas. Não há escrita de perfis, desconexão de usuários ou autorização
de acessos nesta versão. Senhas são criptografadas com Fernet; a chave de
criptografia fica no ambiente/secret manager, separada do banco. Auditar alterações
registra administrador, horário e nomes de campos, sem senhas ou chaves privadas.

Os estados VPN, API e Hotspot são separados. Erros de leitura do servidor não são
apresentados como equipamento offline. Alertas aparecem na central após o atraso
configurado, uma vez por ocorrência/componente, com recuperação registrada.
Não há envio externo de notificações. Disponibilidade mensal usa somente períodos
observados e exibe cobertura; lacunas de worker não viram uptime presumido.

## Privacidade, portal e retenção

Registrar sessões é opt-in administrativo por equipamento e exige finalidade/base
legal documentada e retenção definida. Coletam-se apenas identificação do usuário
Hotspot, equipamento, início/fim, último sinal e bytes transferidos; não há coleta
de páginas visitadas, MAC, documentos ou perfil publicitário nesta integração.
Conectar ao Wi-Fi não significa consentir com marketing.

A prévia de publicidade mostra logotipo e imagens na página de conexão mobile,
com marketing opcional. É privada, não autentica visitantes e não libera internet.
A publicação do portal cativo no MikroTik precisa de integração e homologação
próprias. Imagens PNG são validadas, armazenadas por tenant e servidas sem cache
público; não há diretório público compartilhado de uploads.

Retenção é configurável por tipo. Nenhum prazo jurídico é inventado. Sessões em
aberto não são apagadas por expurgo. A aplicação é manual/agendada:

```sh
python manage.py purge_records          # prévia
python manage.py purge_records --apply  # aplica prazos configurados
```

Revise a finalidade, obrigações, backups, transparência e canal de atendimento.
Controles técnicos ajudam a proteger a operação; não certificam conformidade
LGPD. Veja as páginas públicas de privacidade/termos/retenção.

## Mercado Pago — mensalidade SaaS

A Nova Info recebe de cada estabelecimento uma assinatura mensal pela plataforma.
Os visitantes pagam a internet em dinheiro diretamente ao estabelecimento.
Esse fluxo não recebe nem repassa essas vendas.
O catálogo no Admin fornece o valor da assinatura; planos sem valor positivo
continuam sob consulta, sem inventar preços ou gerar cobranças.

O owner/admin solicita a assinatura em `/painel/assinatura/`, pelo preço exibido.
A proposta de preço é assinada pelo servidor e expira em 15 minutos; uma alteração
no Admin exige nova revisão pelo cliente. Dados de cartão ficam no Mercado Pago.
A solicitação é persistida antes de qualquer chamada externa. O worker cria uma
assinatura pendente de autorização, com frequência de um mês e valor contratado.
O cliente então recebe um link para autorizar a recorrência diretamente no
Mercado Pago. Autorização não é confirmação de pagamento de uma parcela.

Configure credenciais da conta **Nova Info**, collector_id, segredo do webhook e
`MERCADOPAGO_SUBSCRIPTIONS_ENABLED=true` somente após homologação. Por padrão,
essa flag está desativada. Configure eventos `subscription_preapproval`.
Webhook: `/integracoes/mercado-pago/assinaturas/webhook/?data.id=<preapproval_id>`.
O endpoint exige HMAC e consulta a API oficial para confirmar ID, recebedor,
referência, moeda, valor e periodicidade. Não confia no retorno do navegador.
Se o produto/conta entregar notificações sem assinatura, não desative a validação;
use a reconciliação pelo worker até revisar a configuração com o provedor.

```sh
python manage.py process_saas_subscriptions
python manage.py reconcile_saas_subscription ID_MERCADO_PAGO
```

Falhas ambíguas de criação ficam em revisão, sem nova cobrança automática.
Workers em `creating` após interrupção também exigem reconciliação, sem repetição
cega. Estado de assinatura é protegido no PostgreSQL: clientes podem solicitar
pelo valor publicado, mas somente a central/worker pode alterar autorização.
A consulta de parcelas pagas e a conciliação financeira recorrente ainda precisam
de implementação/homologação; não são apresentadas como saldo ou faturamento.

## Verificação

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

Os testes PostgreSQL devem usar banco descartável e identidade de migração que
possa criar/assumir um papel NOSUPERUSER NOBYPASSRLS. Eles verificam SQL sem filtro,
escritas cruzadas, contexto, tabelas operacionais, acesso central autorizado e
revogação de permissão. Testes de adaptadores usam respostas controladas para
validar o protocolo/estados sem afirmar homologação de equipamentos reais.
A apresentação responsiva usa CSS local; verificação visual em navegador está
pendente neste ambiente.

Referências técnicas: [API RouterOS](https://manual.mikrotik.com/docs/developer-guides/api/),
[WireGuard RouterOS](https://manual.mikrotik.com/docs/virtual-private-networks/wireguard/),
[WireGuard](https://www.wireguard.com/quickstart/),
[Assinaturas Mercado Pago](https://www.mercadopago.com.br/developers/pt/reference/online-payments/subscriptions/create-preapproval/post),
[princípios LGPD](https://www.gov.br/saude/pt-br/acesso-a-informacao/lgpd/principios).


## Vendas de internet em dinheiro

Em `/painel/vendas/dinheiro/`, owner/admin/staff podem registrar o dinheiro já
recebido pelo estabelecimento. Viewer tem apenas consulta. O plano deve estar
ativo e pertencer ao tenant; o preço e a duração são validados no servidor e
copiados como fotografia da venda. Alterar o plano depois não modifica o registro.

O formulário exige confirmação de recebimento e uma proposta assinada de curta
duração, vinculada ao usuário e tenant. A venda e o recebimento são criados na
mesma transação, com auditoria do responsável e do horário. A chave única de
requisição impede duplicação ao reenviar o mesmo formulário. Há apenas um
recebimento em dinheiro por venda; não há edição desses registros pela interface.
Registros antigos permanecem com forma de pagamento “Não informado”.

Registrar dinheiro não chama o Mercado Pago, não gera Pix e não autoriza o
Hotspot automaticamente. O estabelecimento recebe e mantém essa receita. A
Nova Info cobra somente sua assinatura mensal SaaS pelo Mercado Pago. O registro
interno não substitui um documento fiscal. Não foram criadas vendas fictícias.


## Instalação local do servidor WireGuard

Execute `sudo bash deploy/install-wireguard.sh` no terminal local. O script
instala wireguard-tools, cria wg0 em 10.77.0.1/24, inicia a unidade wg-quick e
configura verificação de status a cada 60 segundos. Configurações existentes
não são sobrescritas; rotas sobrepostas impedem a instalação. A chave privada
fica somente em /etc/wireguard/wg0.conf, com acesso restrito ao root.

O endpoint inicial é o IP LAN 192.168.6.132. Para usar outro host, passe-o como
primeiro argumento do script. Acesso externo aos MikroTiks exige endpoint
acessível e configuração de rede própria; não há abertura automática de firewall,
NAT ou alteração de roteadores. O script não cadastra peers fictícios.

A central indica o estado do servidor pelo arquivo público de status produzido
pelo serviço root. O processo web não recebe privilégios de rede. Só indica
Ativo se serviço, interface, chave pública, porta e IP corresponderem ao cadastro
e a verificação tiver menos de três minutos. Peers e Hotspot mantêm seus estados
independentes. A instalação não está concluída enquanto o comando sudo não for
executado e validado no host.

## Cadastro e recuperação de acesso

`/accounts/cadastro/` cria uma conta com login, e-mail e senha, inicialmente
inativa. A confirmação por e-mail vale por 24 horas e não cria associação nem
concede acesso a estabelecimentos. Após confirmar, um administrador deve
associar o usuário ao estabelecimento pela central/Admin, com o papel adequado.
O cadastro não permite reivindicar um tenant existente digitando seu subdomínio.

Configure `RESEND_API_KEY` e `RESEND_FROM_EMAIL` no ambiente do processo Django;
o remetente deve pertencer a um domínio verificado no Resend. Reinicie o processo
após configurar. Sem essas variáveis o envio não funciona; falhas no cadastro
cancelam a criação da conta para permitir nova tentativa. Integração via
[API oficial Resend](https://resend.com/docs/api-reference/emails/send-email).

`/accounts/recuperar/` envia um link de uso único, válido por uma hora, para
contas ativas. No subdomínio, somente membros ativos desse estabelecimento
recebem o e-mail. A resposta de sucesso não informa se o endereço existe.
Nunca se envia a senha anterior. O link permite definir uma senha nova.

Todas as rotas `/painel/` exigem sessão autenticada e associação ativa. Sessões
expiram em uma hora ou ao fechar o navegador e são restritas ao host. Uma sessão
já autenticada dispensa redigitar a senha até expirar ou sair da conta.
Login, cadastro e recuperação aceitam dez tentativas por IP/rota em 15 minutos.
O cache padrão limita por processo; em produção com vários workers configure
um backend de cache compartilhado e limites também no proxy. Configure HTTPS,
`DJANGO_DEBUG=false` e uma secret key persistente externa para produção.

A área administrativa de aprovação está em `/accounts/painel/`, no domínio
principal, com login em `/accounts/painel/login/`. Exige usuário ativo, staff e
`operations.manage_network`. Lista contas sem associação, bloqueia aprovação
antes da ativação, permite escolher estabelecimento ativo e papel e registra
quem aprovou na auditoria. Associações existentes são gerenciadas pelo link
“Gerenciar acessos aprovados”. Clientes não acessam essa área.
