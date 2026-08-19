import time

import tinytuya

REGIONS = {"us", "eu", "cn", "in"}


class TuyaReaderError(RuntimeError):
    pass


class TuyaReader:
    """Lector de dispositivos Tuya via tinyTuya.

    - Nube: lista dispositivos vinculados y ultimo estado reportado.
    - Local (LAN): consulta directa por el puerto 6668 usando la local_key,
      misma tecnica que los scripts emc/emX.py del flujo de Node-RED.
    """

    def __init__(self, api_key, api_secret, region="us"):
        if region not in REGIONS:
            raise TuyaReaderError("region invalida: " + ", ".join(sorted(REGIONS)))
        self.api_key = api_key
        self.api_secret = api_secret
        self.region = region
        self.cloud = None
        self._devices = None
        self._fetched_at = 0

    # ------------------------------------------------------------------
    def connect(self):
        if self.cloud is None:
            self.cloud = tinytuya.Cloud(
                apiRegion=self.region,
                apiKey=self.api_key,
                apiSecret=self.api_secret,
            )
            # fuerza la obtencion de token/lista para validar credenciales
            self.cloud.getdevices(verbose=False)
        return self.cloud

    def list_devices(self, force=False, device_filter=None):
        if force or self._devices is None or time.time() - self._fetched_at > 60:
            c = self.connect()
            devices = c.getdevices(include_map=True)
            if not isinstance(devices, list):
                raise TuyaReaderError("getdevices devolvio un formato inesperado: %r" % (devices,))
            self._devices = devices
            self._fetched_at = time.time()
        devices = self._devices
        if device_filter:
            devices = [d for d in devices if d.get("id") in device_filter]
        return devices

    # ------------------------------------------------------------------
    @staticmethod
    def _mapping_dict(device):
        """Mapeo dp_id -> code, extraido del 'mapping' que tinyTuya descarga."""
        mapping = device.get("mapping") or {}
        out = {}
        for dp_id, code in mapping.items():
            try:
                out[str(dp_id)] = code
            except Exception:
                out[dp_id] = code
        return out

    @staticmethod
    def _normalize(result, mapping=None):
        """Convierte la respuesta (nube o local) en lista [{code,value,t}]."""
        mapping = mapping or {}
        items = []
        if isinstance(result, list):
            for it in result:
                if isinstance(it, dict) and "code" in it:
                    items.append({
                        "code": it.get("code"),
                        "value": it.get("value"),
                        "t": it.get("t"),
                    })
                else:
                    items.append({"code": "dp", "value": it})
        elif isinstance(result, dict):
            if "dps" in result and isinstance(result["dps"], dict):
                for dp_id, val in result["dps"].items():
                    code = mapping.get(str(dp_id), "dp%s" % dp_id)
                    items.append({"code": code, "value": val, "t": None})
            else:
                skip = {"category", "model", "product_id", "product_name"}
                for k, v in result.items():
                    if k in skip:
                        continue
                    if isinstance(v, dict) and "value" in v:
                        items.append({"code": k, "value": v["value"], "t": v.get("t")})
                    else:
                        items.append({"code": k, "value": v, "t": None})
        return items

    # ------------------------------------------------------------------
    def cloud_status(self, device_id):
        """Ultimo estado reportado a la nube de Tuya."""
        c = self.connect()
        raw = c.getstatus(device_id)
        if not isinstance(raw, dict) or not raw.get("success"):
            msg = raw.get("msg", raw) if isinstance(raw, dict) else raw
            raise TuyaReaderError("estado nube: %r" % (msg,))
        result = raw.get("result", {})
        mapping = {}
        try:
            mapping = self._mapping_dict(next(
                (d for d in self.list_devices() if d.get("id") == device_id), {}
            ))
        except Exception:
            pass
        return self._normalize(result, mapping)

    def local_status(self, device, timeout=6):
        """Consulta directa por LAN (puerto 6668) usando la local_key."""
        dev_id = device.get("id")
        ip = device.get("ip")
        key = device.get("key") or device.get("local_key")
        if not ip or not key:
            raise TuyaReaderError("dispositivo sin IP o local_key para lectura local")
        d = tinytuya.Device(dev_id, ip, key)
        d.set_version(3.3)
        d.set_retry(1)
        try:
            d.set_socketTimeout(timeout)
        except Exception:
            pass
        status = d.status()
        if "Err" in status:
            raise TuyaReaderError("lectura local: Err %s" % status["Err"])
        mapping = self._mapping_dict(device)
        return self._normalize(status, mapping)

    def read(self, device, local_first=True, local_timeout=6):
        """Lee un dispositivo. Devuelve (source, items) donde source es
        'LAN' (lectura local en tiempo real) o 'cloud' (ultimo reportado)."""
        local_first = local_first and bool(device.get("ip")) and bool(device.get("key"))
        if local_first:
            try:
                return "LAN", self.local_status(device, local_timeout)
            except TuyaReaderError:
                pass  # fallback a la nube
            except Exception:
                pass
        return "cloud", self.cloud_status(device.get("id"))
