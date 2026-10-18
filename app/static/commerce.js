document.querySelectorAll('[data-copy]').forEach(button => {
  button.addEventListener('click', async () => {
    const input = document.getElementById(button.dataset.copy);
    try { await navigator.clipboard.writeText(input.value); button.textContent = 'Copied!'; }
    catch { input.select(); button.textContent = 'Select & copy'; }
  });
});
document.querySelectorAll('[data-back]').forEach(button => button.addEventListener('click', () => history.back()));
