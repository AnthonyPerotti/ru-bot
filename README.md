# RU Bot UFSM

Sistema de agendamento de refeicoes para os Restaurantes Universitarios da UFSM (RU I e RU II).

O projeto e composto por:
1. Interface Web: painel visual para definir horarios, campus e credenciais da UFSM.
2. Agendador (Scheduler): processo que roda em segundo plano ou em container, autentica na API mobile oficial da UFSM e efetua as reservas nos horarios determinados.

---

## Arquitetura e Regras de Negocio

O bot monitora os prazos oficiais estabelecidos pela UFSM para cada tipo de refeicao:
- Jantar: agendado as 11:30 do proprio dia (limite 11:30).
- Cafe da manha: agendado as 13:00 do dia anterior (limite 13:00).
- Almoco: agendado as 22:00 do dia anterior (limite 22:00).

### Regras de Restaurantes (RU I vs RU II)
- RU I (Campus I): oferece Cafe da manha, Almoco e Jantar.
- RU II (Campus II): oferece exclusivamente Almoco.
- Se voce selecionar RU II em um dia e marcar tambem Cafe ou Jantar, o bot reserva o Almoco no RU II e direciona o Cafe e o Jantar para o RU I.

---

## Formas de Execucao

### Opcao 1: Execucao Local Simples (Sem Homelab / Windows)

Para quem deseja rodar na propria maquina sem Docker:

1. Dê um duplo clique no arquivo `iniciar.bat` (ou execute `bash iniciar.sh` no Linux/macOS).
2. O script instalara as dependencias do `requirements.txt`, abrira a interface web no navegador (`http://localhost:3456`) e colocara o agendador em execucao.
3. No painel web, clique em "Configuracoes" para salvar sua matricula e senha do Portal UFSM.
4. Ajuste suas preferencias de refeicoes e clique em "Salvar no Computador / Servidor".

### Opcao 2: Container Docker / Homelab / ZimaOS

Para rodar de forma continua em um servidor Homelab, ZimaOS ou maquina com Docker:

1. Clone o repositorio no seu servidor:
   ```bash
   git clone https://github.com/SEU_USUARIO/ru-bot.git
   cd ru-bot
   ```

2. Suba o servico com Docker Compose (ou importe o compose/app customizado no ZimaOS):
   ```bash
   docker compose up -d
   ```

3. Acesse a interface web pelo IP do seu servidor na porta 3456:
   ```
   http://IP_DO_SERVIDOR:3456
   ```

4. Na interface, va em "Configuracoes", cadastre as credenciais da UFSM, monte sua grade semanal e salve.
   O volume mapeado (`./config.json:/app/config.json`) garante que as alteracoes sejam preservadas e aplicadas imediatamente pelo agendador em loop.

Tambem e possivel definir as credenciais diretamente via variaveis de ambiente caso prefira, criando um arquivo `.env` baseado em `.env.example`:
```env
UFSM_USERNAME=sua_matricula
UFSM_PASSWORD=sua_senha
TZ=America/Sao_Paulo
```

---

## Execucao Manual / Teste Pontual

Para disparar uma verificacao imediata sem aguardar os horarios do loop daemon:

```bash
python scheduler.py --once
```

Para testar o agendamento de uma refeicao especifica:
```bash
python scheduler.py --once --meal lunch
```

---

## Estrutura de Arquivos

```
ru-bot/
├── index.html              # Interface web responsiva
├── server.py               # Servidor HTTP local com API para salvar config.json
├── scheduler.py            # Agendador continuo (daemon) e pontual (--once)
├── requirements.txt        # Dependencias Python (requests, pytz, python-dotenv)
├── Dockerfile              # Imagem Docker leve baseada em Alpine
├── docker-compose.yml      # Definicao do servico para Docker / Homelab / ZimaOS
├── iniciar.bat             # Inicializador automatico para Windows
├── iniciar.sh              # Inicializador automatico para Linux / macOS
├── config.json             # Armazenamento de grade semanal e credenciais
└── .env.example            # Exemplo de variaveis de ambiente
```

---

## Aviso Legal

- Este projeto foi desenvolvido para fins educacionais e uso pessoal.
- Lembre-se de cancelar previamente agendamentos caso nao va comparecer ao refeitorio, evitando desperdicio de alimentos e multas no sistema da instituicao.
