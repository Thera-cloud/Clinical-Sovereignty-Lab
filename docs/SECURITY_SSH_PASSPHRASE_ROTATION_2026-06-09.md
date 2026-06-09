# SSH key passphrase rotation — 2026-06-09

**Trigger:** Passphrase may have been exposed in a terminal capture during GREEN log greps.

## Rotate (Mac, local — do this before further production SSH)

```bash
ssh-keygen -p -f ~/.ssh/id_ed25519
```

Enter the **old** passphrase once, then a **new** passphrase. Do not paste passphrases into chat, tickets, or docs.

## Optional: new key pair (if compromise suspected)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_green -C "nathan-green-$(date +%Y%m)"
ssh-copy-id -i ~/.ssh/id_ed25519_green.pub root@68.183.168.75
```

Update `~/.ssh/config` Host for `68.183.168.75` to use `IdentityFile ~/.ssh/id_ed25519_green`. Remove old pubkey from GREEN `~/.ssh/authorized_keys` after verifying login.

## Verify

```bash
ssh -o BatchMode=yes root@68.183.168.75 'echo ok'
```

Must succeed with new passphrase (or ssh-agent) and **no** secret in command history.
