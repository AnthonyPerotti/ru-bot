# RU Bot UFSM

Sistema de agendamento automatico de refeicoes para os Restaurantes Universitarios da UFSM (RU I e RU II).

O projeto e composto por duas partes:
1. Interface Web (hospedada no GitHub Pages): painel visual para voce definir seus horarios e preferencias semanais.
2. Agendador Automatico (GitHub Actions): script em segundo plano que autentica via API da UFSM e agenda as refeicoes nos prazos oficiais.

---

## Como Funciona a Arquitetura

O agendamento nao ocorre imediatamente no momento em que voce clica em Salvar na interface.

1. Voce acessa a interface web e escolhe quais refeicoes quer por dia da semana.
2. Ao clicar em Commitar no GitHub, a interface salva suas escolhas no arquivo config.json do seu repositorio.
3. O GitHub Actions executa o script scheduler.py todos os dias de acordo com os prazos da UFSM.
4. O script autentica na API mobile oficial da UFSM usando suas credenciais (salvas de forma segura nos Secrets) e efetua as reservas.

### Regras de Restaurantes (RU I vs RU II)
- RU I (Campus I): oferece Cafe da manha, Almoco e Jantar.
- RU II (Campus II): oferece exclusivamente Almoco.
- Se voce selecionar RU II em um dia e marcar tambem Cafe ou Jantar, o bot enviara o Almoco para o RU II e automaticamente agendara o Cafe e o Jantar no RU I.

---

## Guia de Configuracao Passo a Passo

### Passo 1: Publicar o Repositorio no seu GitHub
Abra o GitHub Desktop com o projeto ru-bot selecionado e clique no botao Publish repository (ou Push origin).

### Passo 2: Configurar Credenciais da UFSM (Secrets)
Para que o agendador consiga fazer login em seu nome sem expor sua senha publicamente:
1. Acesse o seu repositorio no navegador (github.com/SEU_USUARIO/ru-bot).
2. Va em Settings > Secrets and variables > Actions.
3. Clique em New repository secret e adicione duas variaveis:
   - Nome: UFSM_USERNAME | Valor: sua matricula da UFSM
   - Nome: UFSM_PASSWORD | Valor: sua senha do portal da UFSM

### Passo 3: Ativar a Interface Web (GitHub Pages)
1. No seu repositorio no GitHub, va em Settings > Pages (menu lateral).
2. Na secao Build and deployment > Branch:
   - Selecione a branch: main
   - Selecione a pasta: / (root)
3. Clique em Save.
4. Em instantes, o GitHub gerara o link publico do seu painel (exemplo: https://SEU_USUARIO.github.io/ru-bot).

### Passo 4: Conectar a Interface Web ao Repositorio (PAT)
Para que o painel web consiga salvar suas configuracoes no repositorio:
1. Crie um token no GitHub acessando: https://github.com/settings/tokens/new?description=ru-bot&scopes=repo
2. Marque a permissao repo e clique em Generate token ao final da pagina.
3. Copie o token gerado (comeca com ghp_).
4. Abra o seu site do GitHub Pages (ou o arquivo index.html no seu navegador), clique no botao Config no canto superior direito e preencha:
   - GitHub Token: seu token ghp_...
   - Usuario: seu usuario do GitHub
   - Repositorio: ru-bot
5. Clique em Salvar integracao. Esse token ficara salvo apenas no localStorage do seu navegador.

### Passo 5: Ativar os Workflows no GitHub
1. No seu repositorio no GitHub, acesse a aba Actions.
2. Se houver uma solicitacao para ativar workflows, clique no botao verde de confirmacao (I understand my workflows, go ahead and enable them).

---

## Como Testar e Acompanhar os Logs

Para testar se o agendamento esta funcionando sem precisar esperar o horario automatico:

1. Acesse o seu repositorio no GitHub e va na aba Actions.
2. Na lista lateral esquerda, clique em RU Scheduler.
3. No lado direito, clique no botao Run workflow:
   - Para agendar de verdade (dia seguinte): mantenha dry_run desmarcado e clique em Run workflow.
   - Para apenas testar a leitura das configuracoes sem agendar: marque dry_run como true.
4. Aguarde a execucao aparecer na lista.
5. Clique na execucao para abrir os detalhes.
6. Clique na etapa Schedule RU meals > Run scheduler para visualizar os logs de login, conexao com a API da UFSM e a confirmacao de cada refeicao agendada.

---

## Horarios de Execucao Automatica (Horario de Brasilia - BRT)

O agendador roda automaticamente nos limites estabelecidos pela UFSM:

| Horario (BRT) | Funcao | Prazo Oficial UFSM |
|---|---|---|
| ~22:00 (Seg a Sex) | Agenda o Almoco do dia seguinte | Ate as 22h do dia anterior |
| 13:00 (Seg a Sex) | Agenda o Cafe do dia seguinte | Ate as 13h do dia anterior |
| 11:30 (Seg a Sex) | Agenda o Jantar do proprio dia | Ate as 11h30 do mesmo dia |

---

## Keep-Alive (Prevencao de Desativacao)

O GitHub desativa automaticamente rotinas agendadas (crons) em repositorios que ficam mais de 60 dias sem commits.
Para evitar isso, o workflow keepalive.yml realiza um commit semanal automatico todo domingo as 06:00 BRT, garantindo que o bot continue rodando indefinidamente sem necessidade de intervencao manual.

---

## Estrutura do Projeto

```
ru-bot/
├── index.html              # Interface web (GitHub Pages)
├── config.json             # Preferencias de refeicoes por dia
├── scheduler.py            # Script Python de integracao com a API UFSM
├── requirements.txt        # Dependencias Python (requests, pytz)
└── .github/
    └── workflows/
        ├── schedule.yml    # Rotinas agendadas de reserva
        └── keepalive.yml   # Manutencao de atividade do repositorio
```

## Aviso Legal e Boas Praticas
- Este projeto foi desenvolvido para fins educacionais e uso pessoal.
- Lembre-se de cancelar previamente agendamentos caso nao va comparecer ao refeitorio, evitando multas administrativas e garantindo o reaproveitamento das vagas por outros estudantes.

