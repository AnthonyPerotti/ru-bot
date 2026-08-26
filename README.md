# ru-bot

Agendador automático para o Restaurante Universitário da UFSM, com interface web via GitHub Pages e execução via GitHub Actions.

## Como funciona

O bot usa a API mobile não-documentada do app UFSMDigital (`portal.ufsm.br/mobile/webservice`) para autenticar e agendar refeições de forma programática, sem CAPTCHA.

A configuração é gerenciada por uma interface web que você hospeda no GitHub Pages do próprio repositório e commita diretamente via GitHub API.

## Configuração inicial

### 1. Fork este repositório

Crie um fork para a sua conta no GitHub.

### 2. Adicione os GitHub Secrets

Vá em **Settings → Secrets and Variables → Actions** e adicione:

| Secret | Valor |
|---|---|
| `UFSM_USERNAME` | Sua matrícula UFSM |
| `UFSM_PASSWORD` | Sua senha do portal UFSM |

### 3. Ative o GitHub Pages

Vá em **Settings → Pages** e configure:
- Source: Deploy from a branch
- Branch: `main`, pasta `/` (root)

### 4. Configure pela interface web

Acesse a URL do seu GitHub Pages (ex: `https://seu-usuario.github.io/ru-bot`) e:

1. Clique em **Config** e insira um [Personal Access Token](https://github.com/settings/tokens/new?scopes=repo&description=ru-bot) com escopo `repo`
2. Configure os agendamentos por dia da semana
3. Clique em **Commitar no GitHub**

### 5. Ative os workflows

Na aba **Actions** do repositório, ative os workflows.

Pronto. A partir daí o bot roda sozinho, sem nenhuma intervenção manual.

## Horários de execução (BRT)

| Cron | Horário BRT | Função |
|---|---|---|
| `0 1 * * 2-6` | ~22h | Agendamento do almoço do dia seguinte |
| `0 16 * * 1-5` | 13h | Agendamento do café do dia seguinte |
| `0 14 * * 1-5` | 11h | Agendamento do jantar do mesmo dia |

Você também pode disparar manualmente pelo painel do Actions (com opção dry-run).

## Keep-alive automático

O GitHub desativa workflows agendados em repositórios sem atividade de push por 60 dias.
O workflow `keepalive.yml` commita um timestamp toda semana (domingo 06h BRT) para manter
o repositório ativo e garantir que o agendamento nunca pare de funcionar.

## Estrutura

```
ru-bot/
├── index.html              # Interface web (GitHub Pages)
├── config.json             # Configuração de agendamentos
├── scheduler.py            # Script Python de agendamento
├── requirements.txt        # Dependências
└── .github/
    └── workflows/
        ├── schedule.yml    # Cron jobs de agendamento
        └── keepalive.yml   # Mantém o repositório ativo
```

## Notas

- A API mobile UFSM foi descoberta via engenharia reversa do app UFSMDigital, conforme documentado pelo projeto [jaimeadf/ruina](https://github.com/jaimeadf/ruina)
- Este projeto é para uso pessoal e educacional
- Sempre cancele agendamentos que não for usar, para não desperdiçar vagas
