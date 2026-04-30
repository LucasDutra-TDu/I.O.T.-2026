from mqtt_as import MQTTClient, config
import asyncio
from settings import SSID, password, BROKER, PORT
import dht, machine
import json

# --- Configuración de Hardware ---
d = dht.DHT22(machine.Pin(15))
rele_pin = machine.Pin(16, machine.Pin.OUT)
led_pin = machine.Pin("LED", machine.Pin.OUT) 

DEVICE_ID = "TERMOSTATO_DUTRA"

# --- Configuración Local MQTT ---
config['server'] = BROKER
config['ssid'] = SSID
config['wifi_pw'] = password
config['port'] = PORT
config['ssl'] = True

# --- JSON parametros_dict ---
CONFIG_FILE = "parametros_dict.json"

def load_config():
    """Carga los parámetros desde el archivo. Si no existe, crea uno nuevo."""
    global parametros_dict
    try:
        with open(CONFIG_FILE, "r") as f:
            parametros_dict = json.load(f)
            print("Configuración cargada:", parametros_dict)
    except (OSError, ValueError):
        print("Archivo no encontrado. Creando nuevo parametros_dict.json...")
        save_config()

def save_config():
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(parametros_dict, f)
        print(f"{CONFIG_FILE} guardado con éxito")
    except OSError as e:
        print("Error al guardar la configuración:", e)

# Cargar la configuración al arrancar
load_config()

# Estado inicial del relé en modo manual
if parametros_dict["modo"] == "manual":
    rele_pin.value(parametros_dict["rele"] ^ 1) # XOR para invertir el valor (Activo en LOW)

# Si tiene un valor inválido: apagado
if parametros_dict["rele"] not in (0, 1):
    parametros_dict["rele"] = 1

# --- Tareas Asíncronas ---
async def destellar_led():
    for _ in range(10):
        led_pin.toggle()
        await asyncio.sleep(0.5)
    led_pin.value(0)

async def messages(client):
    global parametros_dict
    async for topic, msg, retained in client.queue:
        t = topic.decode()
        m = msg.decode()
        print(f'Topic: "{t}" Message: "{m}"')

        # --- Extraer valor (Soporta JSON o Texto plano) ---
        valor_limpio = m
        try:
            # Limpiar el string antes de parsear
            m_limpio = m.strip() 
            datos_json = json.loads(m_limpio)
            if isinstance(datos_json, dict) and "msg" in datos_json:
                valor_limpio = datos_json["msg"]
                print(f"JSON parseado correctamente. Valor extraído: {valor_limpio}")
        except ValueError:
            print(f"No es un JSON, asumiendo texto plano: {valor_limpio}")
        
        # Parsear las suscripciones y actualizar el diccionario
        if t.endswith("/setpoint"):
            try:
                nuevo_setpoint = float(valor_limpio)
                if parametros_dict["setpoint"] != nuevo_setpoint:
                    parametros_dict["setpoint"] = nuevo_setpoint
                    param_modificado = "setpoint"
                    hubo_cambio = True
            except ValueError:
                print(f"Error: '{valor_limpio}' no es un número válido para setpoint.")
                
        elif t.endswith("/periodo"):
            try:
                nuevo_periodo = int(valor_limpio)
                if parametros_dict["periodo"] != nuevo_periodo:
                    parametros_dict["periodo"] = nuevo_periodo
                    param_modificado = "periodo"
                    hubo_cambio = True
            except ValueError:
                print(f"Error: '{valor_limpio}' no es un entero válido para periodo.")
                
        elif t.endswith("/modo"):
            # Validamos que sea un modo permitido
            if valor_limpio in ("auto", "manual"):
                if parametros_dict["modo"] != valor_limpio:
                    parametros_dict["modo"] = valor_limpio
                    param_modificado = "modo"
                    hubo_cambio = True
            else:
                print(f"Error: Modo '{valor_limpio}' no reconocido. Usa 'auto' o 'manual'.")
                
        elif t.endswith("/rele"):
            try:
                nuevo_estado = int(valor_limpio)
                if nuevo_estado in (0, 1):
                    if parametros_dict["rele"] != nuevo_estado:
                        parametros_dict["rele"] = nuevo_estado
                        param_modificado = "rele"
                        hubo_cambio = True
                        if parametros_dict["modo"] == "manual":
                            rele_pin.value(parametros_dict["rele"] ^ 1) # XOR para invertir el valor (Activo en LOW)
                            print(f"Relé: {parametros_dict['rele']}")
                else:
                    print(f"Error: Comando de relé '{nuevo_estado}' inválido. Solo 0 o 1.")
            except ValueError:
                print(f"Error: '{valor_limpio}' no es un número válido para relé.")
                
        elif t.endswith("/destello"):
            asyncio.create_task(destellar_led())

        # Si el valor realmente cambió, guardamos y enviamos la notificación
        if hubo_cambio:
            save_config()
            # Lanzamos la notificación por MQTT
            await notificar_cambio(client, param_modificado, parametros_dict[param_modificado])

async def notificar_cambio(client, parametro, nuevo_valor):
    """Publica un JSON confirmando el cambio realizado"""
    topic_notificacion = f"{DEVICE_ID}/notificaciones"
    payload = json.dumps({
        "evento": "parametro_actualizado",
        "parametro": parametro,
        "valor": nuevo_valor
    })
    await client.publish(topic_notificacion, payload, qos=1)
    print(f"✅ Notificación enviada: {parametro} -> {nuevo_valor}")

async def up(client):
    while True:
        await client.up.wait()
        client.up.clear()
        topicos = ["setpoint", "periodo", "destello", "modo", "rele"]
        for t in topicos:
            await client.subscribe(f'{DEVICE_ID}/{t}', 1)

async def main(client):
    await client.connect()
    for coroutine in (up, messages):
        asyncio.create_task(coroutine(client))

    while True:
        try:
            d.measure()
            try:
                temperatura = d.temperature()
                humedad = d.humidity()
                
                # --- Lógica del Termostato ---
                if parametros_dict["modo"] == "auto":
                    print(f"Temperatura medida: {temperatura}. Setpoint: {parametros_dict['setpoint']} grados.")
                    if temperatura > parametros_dict["setpoint"]:
                        print("Rele ON.")
                        rele_pin.value(0)
                    else:
                        print("Rele OFF.")
                        rele_pin.value(1)
                        
                # --- Publicación de JSON ---
                # Agregamos las lecturas al diccionario existente o creamos uno nuevo para enviar
                payload = json.dumps({
                    "temperatura": temperatura,
                    "humedad": humedad,
                    "setpoint": parametros_dict["setpoint"],
                    "periodo": parametros_dict["periodo"],
                    "modo": parametros_dict["modo"]
                })
                
                await client.publish(f'{DEVICE_ID}', payload, qos=1)
                
            except OSError as e:
                print("Error de lectura del sensor DHT:", e)
        except OSError as e:
            print("Sensor no encontrado")
            
        for _ in range(parametros_dict["periodo"]):
            await asyncio.sleep(1)

config["queue_len"] = 1
MQTTClient.DEBUG = False
client = MQTTClient(config)

try:
    asyncio.run(main(client))
finally:
    client.close()