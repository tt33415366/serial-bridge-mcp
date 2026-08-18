(() => {
  const hubUrl = document.getElementById("hub-url");
  const authNote = document.getElementById("auth-note");
  const tokenSection = document.getElementById("token-section");
  const snippetSection = document.getElementById("snippet-section");
  const remoteNote = document.getElementById("remote-note");
  const accessToken = document.getElementById("access-token");
  const cursorSnippet = document.getElementById("cursor-snippet");
  const envWarning = document.getElementById("env-warning");
  const btnCopyToken = document.getElementById("btn-copy-token");
  const btnCopySnippet = document.getElementById("btn-copy-snippet");
  const btnRotate = document.getElementById("btn-rotate-token");

  function showLoopback(data) {
    tokenSection.hidden = false;
    snippetSection.hidden = false;
    remoteNote.hidden = true;
    accessToken.textContent = data.token;
    cursorSnippet.textContent = data.cursor_snippet;
    envWarning.hidden = !data.env_override;
    envWarning.textContent = data.warning || "";
  }

  function showRemote() {
    tokenSection.hidden = true;
    snippetSection.hidden = true;
    remoteNote.hidden = false;
    envWarning.hidden = true;
  }

  async function loadSetup() {
    const response = await fetch("/api/setup");
    const data = await response.json();
    hubUrl.textContent = data.hub_url;
    authNote.textContent = data.auth_note;
    if (data.loopback) {
      showLoopback(data);
    } else {
      showRemote();
    }
  }

  async function copyText(text, button) {
    await navigator.clipboard.writeText(text);
    const original = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => {
      button.textContent = original;
    }, 1200);
  }

  btnCopyToken.addEventListener("click", () => {
    copyText(accessToken.textContent, btnCopyToken);
  });

  btnCopySnippet.addEventListener("click", () => {
    copyText(cursorSnippet.textContent, btnCopySnippet);
  });

  btnRotate.addEventListener("click", async () => {
    btnRotate.disabled = true;
    try {
      const response = await fetch("/api/setup/rotate", { method: "POST" });
      if (!response.ok) {
        throw new Error(`Rotate failed (${response.status})`);
      }
      const data = await response.json();
      showLoopback(data);
    } catch (error) {
      authNote.textContent = `Rotate failed: ${error.message}`;
    } finally {
      btnRotate.disabled = false;
    }
  });

  loadSetup().catch((error) => {
    authNote.textContent = `Setup failed: ${error.message}`;
  });
})();
