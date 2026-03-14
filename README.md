# ⚡ LAN Transfer

P2P encrypted file transfer over your local network. No internet needed.

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Open `http://<your-ip>:5000` in browser.  
Other devices on the same LAN can open `http://<your-ip>:5000` too.

## How it works

1. **Set a password** - all devices must use the SAME password
2. **Auto-discovery** - devices broadcast their presence on UDP port 55555
3. **Select a peer** - discovered devices show up automatically  
4. **Send a file** - gets AES-256 encrypted before transfer
5. **Receive** - automatically decrypted and saved to `uploads/` folder

## Security

- AES-256-CBC encryption (pycryptodome)
- Password hash verified before any file is accepted
- Files are encrypted on sender side, decrypted on receiver side
- Random IV per transfer

## Notes

- All devices need to be on the same LAN/WiFi
- All devices need to run `python app.py`
- All devices need to use the **same password**
- Files are saved in the `uploads/` folder
- Max file size: 2GB (change in app.py if needed)

## Troubleshooting

- **Peer not showing up**: Make sure firewall isn't blocking UDP 55555 or TCP 5000
- **Decryption failed**: Wrong password — both sides must use the same one
- **Connection refused**: Target device might not be running the app
# LAN-File-Transfer
