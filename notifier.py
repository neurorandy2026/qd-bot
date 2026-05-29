import aiohttp


async def send_webhook(webhook_url: str, content: str) -> bool:
    if not webhook_url:
        print("[Notifier] No webhook URL configurado")
        return False

    async with aiohttp.ClientSession() as session:
        async with session.post(webhook_url, json={"content": content}) as resp:
            if resp.status not in (200, 204):
                text = await resp.text()
                error_msg = f"HTTP {resp.status}: {text[:200]}"
                print(f"[Notifier] Error Discord: {error_msg}")
                return False
            return True


async def test_webhook(webhook_url: str) -> str:
    """Returns error description or 'OK'."""
    if not webhook_url:
        return "URL vacia"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json={"content": "🔧 Test de conexion"}) as resp:
                text = await resp.text()
                return f"OK ({resp.status})" if resp.status in (200, 204) else f"Error {resp.status}: {text[:150]}"
    except Exception as e:
        return f"Exception: {str(e)}"
