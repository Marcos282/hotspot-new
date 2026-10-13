const menuToggle = document.querySelector(".menu-toggle");
const mainNav = document.querySelector(".main-nav");

if (menuToggle && mainNav) {
  menuToggle.addEventListener("click", () => {
    const isOpen = menuToggle.getAttribute("aria-expanded") === "true";
    menuToggle.setAttribute("aria-expanded", String(!isOpen));
    menuToggle.setAttribute("aria-label", isOpen ? "Abrir menu" : "Fechar menu");
    mainNav.classList.toggle("is-open", !isOpen);
  });

  mainNav.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      menuToggle.setAttribute("aria-expanded", "false");
      menuToggle.setAttribute("aria-label", "Abrir menu");
      mainNav.classList.remove("is-open");
    });
  });
}

if (menuToggle && mainNav) {
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && mainNav.classList.contains("is-open")) {
      mainNav.classList.remove("is-open");
      menuToggle.setAttribute("aria-expanded", "false");
      menuToggle.setAttribute("aria-label", "Abrir menu");
      menuToggle.focus();
    }
  });
}
function calculateRevenue(accesses, price, days) {
  if (![accesses, price, days].every(Number.isFinite) || accesses < 0 || accesses > 1000000 || !Number.isInteger(accesses) || price < 0 || price > 1000000 || days < 1 || days > 31 || !Number.isInteger(days)) return null;
  return accesses * price * days;
}
const simulationFields = ["daily-access", "average-price", "operating-days"].map(id => document.getElementById(id));
if (simulationFields.every(Boolean)) {
  const update = () => {
    const valid = simulationFields.every(field => field.value.trim() !== "" && field.checkValidity());
    const revenue = valid ? calculateRevenue(...simulationFields.map(field => Number(field.value))) : null;
    document.getElementById("monthly-revenue").textContent = revenue === null ? "—" : revenue.toLocaleString("pt-BR", {style:"currency", currency:"BRL"});
    document.getElementById("simulation-error").textContent = revenue === null ? "Informe acessos inteiros, um valor positivo ou zero e entre 1 e 31 dias." : "";
  };
  simulationFields.forEach(field => field.addEventListener("input", update));
  update();
}
