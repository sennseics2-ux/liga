# Liga SX-AAC V22

## What's new
- Removed the standalone **View transfer market** link from the homepage transfer section. The transfer-market section, individual auction links, and the Transfer market navigation item remain intact.
- Swapped homepage discovery links: Players → **Explore teams**; Managers → **Explore players**.
- Applied the logo-inspired black / grey / white design to all website sections: public directories, auctions, standings, profiles, admin, forms and PGN replay.
- Preserved the existing European Portuguese (Portugal) and English language catalogue.
- No database schema changes.

## Update on Google Cloud
Back up `data/league.sqlite3` and verify an off-server copy. After uploading the ZIP via SSH:

```bash
cd ~
unzip -q chess-fantasy-league-v22.zip
cd /opt/clubdraft
sudo docker compose exec -T web python -m deploy.backup_sqlite
sudo docker compose down
sudo rsync -a --exclude='/.env' --exclude='/data/' --exclude='/backups/' \
  ~/chess-fantasy-league-v22/ /opt/clubdraft/
sudo docker compose up -d --build
sudo docker compose ps
```

If the archive was already extracted, delete or move the extracted **V22 source directory only** before unzipping again. Never overwrite your server's `.env`, `data/` or `backups/`.
