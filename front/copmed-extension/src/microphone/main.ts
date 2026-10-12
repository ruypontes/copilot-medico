// Página de permissão do microfone (B29).
//
// A gravação roda em um documento offscreen, que não consegue exibir o pedido de permissão, e
// o popup fecha quando o navegador tenta exibi-lo. A permissão vale para a extensão inteira,
// então basta concedê-la uma vez nesta aba.

const status = document.getElementById("status") as HTMLParagraphElement;
const button = document.getElementById("permitir") as HTMLButtonElement;

async function requestMicrophone() {
  status.textContent = "Aguardando a sua resposta ao pedido do navegador...";
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((track) => track.stop()); // só a permissão interessa aqui
    button.hidden = true;
    status.textContent =
      "✅ Microfone liberado. Feche esta aba, abra o CopMed e clique em “Iniciar gravação”.";
  } catch (error) {
    const name = error instanceof Error ? error.name : "";
    status.textContent =
      name === "NotFoundError"
        ? "❌ Nenhum microfone encontrado. Conecte um microfone e tente de novo."
        : "❌ Permissão negada. Clique no ícone à esquerda do endereço desta aba, libere o " +
          "microfone e clique em “Permitir microfone” novamente.";
  }
}

button.addEventListener("click", requestMicrophone);
requestMicrophone();
