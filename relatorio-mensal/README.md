# Relatório financeiro mensal (Agência do Futuro)

Todo dia 1, às 08:00 (horário de Brasília), este script:

1. lê a planilha "Futuro 2026" (só leitura, não altera nada);
2. analisa o mês que acabou de fechar e o acumulado do ano;
3. manda pelo bot do Telegram um resumo curto e dois painéis em anexo (`painel-AAAA-MM.html` e `retiradas-AAAA-MM.html`, que abrem no navegador do celular).

Ele usa o mesmo token e a mesma conta de serviço do Google que o bot já usa.

## Passo a passo

### 1. Colocar esta pasta no repositório do bot
No GitHub, abra `brunorestum/telegram-flight-bot` → **Add file → Upload files** e arraste a pasta `relatorio-mensal` inteira: `relatorio.py`, `requirements.txt`, `README.md` e a pasta `templates` com 3 arquivos. Depois clique em **Commit changes**.

O bot não muda: esta pasta só é usada pelo Cron Job.

### 2. Descobrir o seu chat id do Telegram
No Telegram, abra o **@userinfobot** e mande qualquer mensagem. Ele responde com o seu `Id` (um número). Esse número é o `TELEGRAM_CHAT_ID`.

Antes do primeiro envio, mande um `/start` para o seu bot (se já conversou com ele, pode pular).

### 3. Criar o Cron Job no Render
Render → **New → Cron Job** → escolha o repositório `telegram-flight-bot`.

| Campo | Valor |
|---|---|
| Name | `relatorio-mensal` |
| Root Directory | `relatorio-mensal` |
| Runtime / Language | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Command | `python relatorio.py` |
| Schedule | `0 11 1 * *` (todo dia 1 às 11:00 UTC, ou seja, 08:00 em Brasília) |

### 4. Variáveis de ambiente do Cron Job
| Variável | O que colocar |
|---|---|
| `TELEGRAM_BOT_TOKEN` | o mesmo do bot |
| `GOOGLE_CREDENTIALS_JSON` | o mesmo do bot (o JSON inteiro) |
| `GOOGLE_SHEET_ID` | o mesmo do bot (id da "Futuro 2026") |
| `TELEGRAM_CHAT_ID` | o número do passo 2 |
| `SALDO_10X_PIX` | saldo a receber do 10x pix, ex.: `38870.27` |
| `SALDO_10X_PIX_DATA` | data desse saldo, ex.: `29/09/2026` |

Dica: no Render, dá para criar um **Environment Group** com as 3 primeiras variáveis e ligar ao bot e ao Cron Job. Assim, quando o token mudar, você troca num lugar só.

### 5. Rodar agora
Na página do Cron Job, clique em **Trigger Run**. Se a data não for dia 1, 2 ou 3, ele analisa o mês atual como **parcial**. Em um ou dois minutos, a mensagem e os dois painéis chegam no seu Telegram.

## Todo mês
- Antes do dia 1, atualize `SALDO_10X_PIX` e `SALDO_10X_PIX_DATA` no Render. Esse saldo não está na planilha. Se não atualizar, a mensagem avisa.
- Em janeiro de 2027: a execução de 01/01/2027 ainda analisa dezembro de 2026. Depois dela, troque `GOOGLE_SHEET_ID` para a planilha "Futuro 2027".

## Se der erro
- **403 ao ler a planilha**: no Google Cloud do projeto da conta de serviço, ative a **Google Drive API** (o bot só usa a Sheets API). Confira também se a planilha está compartilhada com o e-mail da conta de serviço.
- **400 "chat not found" no Telegram**: você ainda não mandou `/start` para o bot, ou o `TELEGRAM_CHAT_ID` está errado.
- Os logs ficam na aba **Logs** do Cron Job no Render.

## Testar no computador (sem enviar nada)
```
pip install -r requirements.txt
LOCAL_XLSX=/caminho/Futuro2026.xlsx DRY_RUN=1 python relatorio.py
```
Os arquivos saem na pasta `saida/`. A variável `HOJE=2026-10-01` simula a data da execução.
