import aiohttp


async def send_webhook(webhook_url: str, content: str) -> bool:
    if not webhook_url:
        print("[Notifier] No webhook URL configurado")
        return False

    async with aiohttp.ClientSession() as session:
        async with session.post(webhook_url, json={"content": content}) as resp:
            if resp.status not in (200, 204):
                text = await resp.text()
                print(f"[Notifier] Error Discord: {resp.status} — {text[:150]}")
                return False
            return True
