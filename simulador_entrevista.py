import asyncio
import os
import json
import re
import streamlit as st
from pypdf import PdfReader
from groq import Groq
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dotenv import load_dotenv
load_dotenv()

github_api_key = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")

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
        server_params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={
                **os.environ,
                "GITHUB_PERSONAL_ACCESS_TOKEN": os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", github_api_key)
            }
        )
        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    resultado_mcp = await session.call_tool("search_repositories", arguments={"query": f"user:{self.usuario}"})
                    
                    texto_github = ""
                    for content_item in resultado_mcp.content:
                        if hasattr(content_item, "text"):
                            texto_github += content_item.text + "\n"
                    return texto_github
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
# PROCESAMIENTO ASÍNCRONO DE LA PREGUNTA
# ==========================================
async def procesar_respuesta_agente(pregunta):
    datos_cv = st.session_state.agente_cv.extraer_informacion_relevante(pregunta)
    datos_github = "El reclutador está dando seguimiento o evaluando otros aspectos."
    
    palabras_clave_mcp = ["github", "repositorio", "repositorios", "proyectos", "código", "trabajado", "trabajaste", "commit"]
    if any(palabra in pregunta.lower() for palabra in palabras_clave_mcp):
        # Si requiere GitHub, ejecutamos de manera asíncrona optimizada
        print("🔍 Conectando al Servidor MCP de GitHub en tiempo real...")
        datos_github = await st.session_state.agente_github.consultar_repositorios_reales()


    instrucciones_sistema = f"""
    Eres Delma, una Senior Data Engineer experta en automatización e IA. Estás en una entrevista de trabajo crucial con un reclutador o líder técnico de BANORTE. 
    Tu objetivo es consolidar la información disponible de tus agentes de soporte y responder de forma directa, entusiasta, empática y con mucha seguridad.

    INSTRUCCIONES CRÍTICAS DE ESTILO CONVERSACIONAL:
    - Responde inmediatamente en primera persona como si estuvieras en una videollamada en vivo.
    - PROHIBIDO usar preámbulos robóticos o etiquetas de sistema. Ve directo a tu argumento técnico o respuesta.
    - GESTIÓN CONVERSACIONAL DE PROYECTOS (Antirrepetición): Si te preguntan por proyectos o por tu GitHub, y el reporte técnico no muestra repositorios públicos, responde con naturalidad basándote en la arquitectura de tus soluciones de tu CV. Describe de manera fluida CÓMO diseñas (estructuras de DAGs en Airflow, validación con Claude/MCPs, o ingesta en Azure Spark) en lugar de dar explicaciones o disculpas de por qué el código es privado. Habla del "cómo" y del impacto de negocio directamente.
    - VARIABILIDAD: Está estrictamente PROHIBIDO recitar párrafos memorizados sobre "protocolos estrictos de seguridad de Visa" o "integridad de la información empresarial". Si necesitas mencionar el entorno confidencial, dilo en una sola frase casual y salta de inmediato a explicar la lógica de tus pipelines.
    - ENCUADRE DE TU PERFIL (Geofísica + Data): Tu ingeniería te dio la rigurosidad matemática y el modelado de riesgo, mientras que tu Maestría y tus 4 años en Visa consolidaron tu perfil técnico.
    - Si vas a estructurar puntos, hazlo de forma hablada. PROHIBIDO usar viñetas (bullet points) o listas numeradas rígidas.
    - REMATE Y CIERRE: Termina tu respuesta de forma tajante en un máximo de 3 o 4 oraciones totales.

    --------------------------------------------------
    CONOCIMIENTO ACTUALIZADO DEL PDF DE TU CV:
    {datos_cv}
    --------------------------------------------------
    CONOCIMIENTO EN TIEMPO REAL DE TU GITHUB:
    {datos_github}
    --------------------------------------------------
    """

    payload = [{"role": "system", "content": instrucciones_sistema}]
    for msg in st.session_state.messages:
        # Mapeamos los roles visuales a los roles que entiende Groq
        role_map = "user" if msg["role"] == "user" else "assistant"
        payload.append({"role": role_map, "content": msg["content"]})
    
    payload.append({"role": "user", "content": pregunta})

    chat_completion = client.chat.completions.create(
        messages=payload,
        model="qwen/qwen3.8-27b",
        temperature=0.7,
        max_tokens=450,
    )
    return chat_completion.choices[0].message.content

# ==========================================
# ÁREA DE ENTRADA DEL USUARIO (INTERFAZ)
# ==========================================
if pregunta_entrevistador := st.chat_input("Escribe aquí la pregunta del entrevistador de Banorte..."):
    
    # 1. Mostrar la pregunta del usuario con diseño de "usuario"
    with st.chat_message("user"):
        st.markdown(pregunta_entrevistador)
    
    # Guardar en el historial interno
    st.session_state.messages.append({"role": "user", "content": pregunta_entrevistador})
    
    # 2. Procesar y mostrar la respuesta de Delma en tiempo real
    with st.chat_message("assistant", avatar="✨"):
        with st.spinner("Delma está pensando su respuesta..."):
            # Corremos la función asíncrona dentro del ecosistema síncrono de Streamlit
            respuesta_delma = asyncio.run(procesar_respuesta_agente(pregunta_entrevistador))
            st.markdown(respuesta_delma)
            
    # Guardar la respuesta de la asistente en el historial
    st.session_state.messages.append({"role": "assistant", "content": respuesta_delma})
