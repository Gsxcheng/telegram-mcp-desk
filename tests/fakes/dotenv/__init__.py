import os


def load_dotenv(path=None, override=False):
    if not path or not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"')
            if override or k not in os.environ:
                os.environ[k.strip()] = v
    return True
