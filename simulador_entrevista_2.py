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
            # Creamos un loop de eventos limpio para evitar la doble ejecución en terminal
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            respuesta_delma = loop.run_until_complete(procesar_respuesta_agente(pregunta_entrevistador))
            loop.close()
            
            st.markdown(respuesta_delma)
            
    st.session_state.messages.append({"role": "assistant", "content": respuesta_delma})
