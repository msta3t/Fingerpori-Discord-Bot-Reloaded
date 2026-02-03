# Fingerpori-Discord-Bot-Reloaded
Retrieves today’s Fingerpori comic from the Helsingin Sanomat website and sends it to a Discord channel via a webhook.

Logic to find comic and get around HS bot detection is vibe coded with Gemini. 

Expect this to break often as HS constanly changes their site :)

## fingerpori_bot usage
Paste your guild id in .env.default and rename to .env

Create new application at https://discord.com/developers/applications

In **Settings** -> **Installation** 
- Uncheck **User Install** in Installation Contexts
- Set **Install Link** to **None**

In **Settings** -> **Bot**
- Click **Reset Token** and copy it to .env
- Disable **Public Bot**
- Enable **Presence Intent**
- Enable **Message Content Intent**

In **Settings** -> **OAuth2**
- Check in **Scope**:
  - **bot**
  - **applications.commands**
-  Check in **Bot Permissions** -> **Text Permissions**:
   -  **Send Messages**
   -  **Read Message History**
- Open generated URL to add the bot to your server

Run the bot and use /set_channel in the channel you wish to receive comics in. 

Restart the bot and it should post a new comic every day. 
Use /scrape to force the bot to get a comic if a new one is available.

## fingerpori_scraper usage
You can also run fingerpori_scraper.py by itself

Make a new webhook url in Discord Server Settings -> Integrations -> Webhook

Paste it into .env.default and rename it to .env

Schedule fingerpori_scraper.py to run once every day with a cronjob or something