import asyncio
import os
import json
import re
import platform  # <-- Añade este import
import streamlit as st
from pypdf import PdfReader
from groq import Groq
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import shutil

from dotenv import load_dotenv
load_dotenv()

# ==========================================
# CONFIGURACIÓN DE LA PÁGINA (STREAMLIT)
# ==========================================
st.set_page_config(page_title="Simulador de Entrevista - Banorte", page_icon="🤖", layout="centered")
st.title("🎙️ Simulador de Entrevista: Delma vs Banorte")
st.caption("Arquitectura Multi-Agente con RAG (CV PDF) y Conector MCP GitHub")

# 3. Inicializar el cliente tomando la variable de entorno de forma segura
@st.cache_resource
def get_groq_client():
    # os.environ.get buscará la variable tanto en tu sistema local (.env) como en los entornos de producción
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        st.error("❌ ERROR: No se encontró la variable de entorno GROQ_API_KEY.")
    return Groq(api_key=api_key)

client = get_groq_client()

# ==========================================
# MODELO DE DATOS Y COMPONENTES REUTILIZABLES
# ==========================================
class AgenteCV:
    def __init__(self, ruta_pdf):
        self.ruta_pdf = ruta_pdf
        self.chunks = []
        self._inicializar_rag()

    def _inicializar_rag(self):
        if not os.path.exists(self.ruta_pdf):
            raise FileNotFoundError(f"No se encontró el archivo: {self.ruta_pdf}")
        reader = PdfReader(self.ruta_pdf)
        texto_completo = ""
        for pagina in reader.pages:
            texto_pagina = pagina.extract_text()
            if texto_pagina:
                texto_completo += texto_pagina + "\n"
        
        palabras = texto_completo.strip().split()
        i = 0
        while i < len(palabras):
            chunk = " ".join(palabras[i:i + 400])
            self.chunks.append(chunk)
            i += 400 - 50

    def extraer_informacion_relevante(self, consulta):
        palabras_clave = set(re.findall(r'\w+', consulta.lower()))
        conectores = {'el', 'la', 'los', 'las', 'un', 'una', 'en', 'de', 'del', 'que', 'es', 'son', 'cual', 'cuales'}
        palabras_clave = palabras_clave - conectores
        
        puntuaciones = []
        for chunk in self.chunks:
            coincidencias = sum(1 for palabra in palabras_clave if palabra in chunk.lower())
            puntuaciones.append((coincidencias, chunk))
        
        puntuaciones.sort(key=lambda x: x[0], reverse=True)
        return puntuaciones[0][1] if puntuaciones and puntuaciones[0][0] > 0 else "Usa tu conocimiento general del CV de Delma."

class AgenteGitHub:
    def __init__(self, usuario):
        self.usuario = usuario
    async def consultar_repositorios_reales(self):
        import platform
        import os
        import shutil
        
        # 1. Determinar el comando correcto según el entorno (Local vs Nube)
        if platform.system() == "Windows":
            nombre_cmd = "npx.cmd"
            ruta_ejecutable = shutil.which(nombre_cmd) or shutil.which("npx")
            if not ruta_ejecutable:
                ruta_posible = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "nodejs", "npx.cmd")
                if os.path.exists(ruta_posible):
                    ruta_ejecutable = ruta_posible
        else:
            # Entorno de producción en Streamlit Cloud (Linux)
            nombre_cmd = "npx"
            ruta_ejecutable = shutil.which(nombre_cmd)
            
            # PARCHE PARA LA NUBE: Si Linux no encuentra 'npx' en el PATH básico, buscamos en rutas comunes
            if not ruta_ejecutable:
                rutas_comunes_linux = [
                    "/usr/bin/npx",
                    "/usr/local/bin/npx",
                    "/home/appuser/.npm-global/bin/npx",
                    "/usr/sbin/npx"
                ]
                for ruta in rutas_comunes_linux:
                    if os.path.exists(ruta):
                        ruta_ejecutable = ruta
                        break

        if not ruta_ejecutable:
            return "Error: No se encontró 'npx' en el entorno de ejecución. Revisa packages.txt en la nube."
        
        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    resultado_mcp = await session.call_tool("search_repositories", arguments={"query": f"user:{self.usuario}"})
                    
                    texto_github = ""
                    for content_item in resultado_mcp.content:
                        if hasattr(content_item, "text"):
                            texto_github += content_item.text + "\n"
                    return texto_github if texto_github.strip() else "No se encontraron repositorios públicos."
        except Exception as e:
            return f"Error al extraer datos de GitHub mediante el Servidor MCP: {e}"

# Instanciar agentes en el estado de la sesión si no existen
if "agente_cv" not in st.session_state:
    try:
        st.session_state.agente_cv = AgenteCV("cv_delma_diaz.pdf")
        st.session_state.agente_github = AgenteGitHub("Delma2510")
    except Exception as e:
        st.error(f"Falta el archivo PDF o configuración: {e}")

# Inicializar historial de chat visual
if "messages" not in st.session_state:
    st.session_state.messages = []

# Redibujar la conversación histórica en la pantalla
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ==========================================
# PROCESAMIENTO ASÍNCRONO DE LA PREGUNTA (CORREGIDO)
# ==========================================
async def procesar_respuesta_agente(pregunta):
    datos_cv = st.session_state.agente_cv.extraer_informacion_relevante(pregunta)
    datos_github = "El reclutador está dando seguimiento o evaluando otros aspectos."
    
    palabras_clave_mcp = ["github", "repositorio", "repositorios", "proyectos", "código", "trabajado", "trabajaste", "commit"]
    requiere_github = any(palabra in pregunta.lower() for palabra in palabras_clave_mcp)
    
    if requiere_github:
        print("🔍 Conectando al Servidor MCP de GitHub en tiempo real...")
        datos_github = await st.session_state.agente_github.consultar_repositorios_reales()

    instrucciones_sistema = f"""
    Eres Delma, una Senior Data Engineer experta en automatización e IA. Estás en una entrevista de trabajo con BANORTE. 
    Responde en primera persona, con seguridad y entusiasmo.

    INSTRUCCIONES DE ESTILO CONVERSACIONAL:
    - Ve directo al grano, sin preámbulos robóticos ni etiquetas de sistema.
    - Si en los datos en tiempo real de GitHub se muestra información de repositorios o commits, úsalos inmediatamente para responder la pregunta de forma concreta.
    - GESTIÓN DE PROYECTOS PRIVADOS: Solo si el reporte técnico de GitHub viene vacío o con errores, explica cómo estructuras tus soluciones (DAGs en Airflow, validación con Claude/MCPs, o ingesta en Azure Spark) sin disculparte.
    - No uses viñetas (bullet points) ni listas numeradas rígidas.
    - Termina en un máximo de 3 o 4 oraciones totales.

    --------------------------------------------------
    CONOCIMIENTO ACTUALIZADO DEL PDF DE TU CV:
    {datos_cv}
    --------------------------------------------------
    DATOS EN TIEMPO REAL DE TU GITHUB (Usa esto si te preguntan por repositorios/commits):
    {datos_github}
    --------------------------------------------------
    """

    payload = [{"role": "system", "content": instrucciones_sistema}]
    
    # Filtrar el historial para que no repita en bucle el mensaje memorizado antiguo
    for msg in st.session_state.messages[:-1]:  # Excluimos la pregunta actual que ya se guardó
        role_map = "user" if msg["role"] == "user" else "assistant"
        # Si el asistente respondió antes el texto genérico de Visa, lo suavizamos para no sesgar al modelo
        if "estrictos protocolos de seguridad de Visa" in msg["content"]:
            continue
        payload.append({"role": role_map, "content": msg["content"]})
    
    # Modificación crítica: Inyectar el contexto de GitHub directamente en el último input del usuario
    if requiere_github:
        payload.append({
            "role": "user", 
            "content": f"Pregunta: {pregunta}\n\n[CONTEXTO DE MI GITHUB ACTUAL EN TIEMPO REAL]:\n{datos_github}"
        })
    else:
        payload.append({"role": "user", "content": pregunta})

    chat_completion = client.chat.completions.create(
        messages=payload,
        model="qwen/qwen3.8-27b",
        temperature=0.3,  # Bajamos la temperatura para que sea más determinista con los datos provistos
        max_tokens=450,
    )
    return chat_completion.choices[0].message.content

# ==========================================
# ÁREA DE ENTRADA DEL USUARIO (INTERFAZ OPTIMIZADA)
# ==========================================
if pregunta_entrevistador := st.chat_input("Escribe aquí la pregunta del entrevistador de Banorte..."):
    
    # 1. Mostrar y guardar la pregunta del usuario
    with st.chat_message("user"):
        st.markdown(pregunta_entrevistador)
    
    # Evitar duplicaciones guardando limpiamente en el estado
    st.session_state.messages.append({"role": "user", "content": pregunta_entrevistador})
    
    # 2. Procesar respuesta controlando el loop de Streamlit
    with st.chat_message("assistant", avatar="✨"):
        with st.spinner("Delma está pensando su respuesta..."):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Traemos los datos crudos de GitHub para auditoría
            datos_github_debug = loop.run_until_complete(st.session_state.agente_github.consultar_repositorios_reales())
            
            # Mostramos un expansor en Streamlit para verificar qué está leyendo la IA
            with st.expander("🛠️ Depuración MCP: Datos crudos de GitHub"):
                st.code(datos_github_debug, language="text")
            
            # Corremos la respuesta final del agente
            respuesta_delma = loop.run_until_complete(procesar_respuesta_agente(pregunta_entrevistador))
            loop.close()
            
            st.markdown(respuesta_delma)
            
    st.session_state.messages.append({"role": "assistant", "content": respuesta_delma})
