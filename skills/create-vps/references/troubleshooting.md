# Troubleshooting

## `hcloud` unauthorized

The token is missing, revoked, or lacks Read & Write permission.

Create a new token and paste it into `.env`.

## SSH host key warning

If the server was rebuilt and the IP reused:

```bash
ssh-keygen -R <ip>
```

## Server type unavailable

Use `hcloud server-type list` and `hcloud location list`.

Availability changes by location.

## SSH alias does not work

Check:

```bash
cat ~/.ssh/config
ssh -v <alias>
```