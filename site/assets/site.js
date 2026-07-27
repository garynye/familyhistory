const searchDialog = document.querySelector("[data-search-dialog]");
const searchInput = document.querySelector("#site-search");
const searchResults = document.querySelector("[data-search-results]");
let searchIndex = [];

document.querySelectorAll("[data-search-open]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (!searchIndex.length) {
      searchIndex = await fetch("/search-index.json").then((response) => response.json());
    }
    searchDialog.showModal();
    searchInput.focus();
  });
});

searchInput?.addEventListener("input", () => {
  const query = searchInput.value.trim().toLocaleLowerCase();
  if (query.length < 2) {
    searchResults.innerHTML = "<p>Enter at least two letters to search the archive.</p>";
    return;
  }

  const terms = query.split(/\s+/);
  const matches = searchIndex
    .map((item) => {
      const haystack = `${item.title} ${item.collection} ${item.text}`.toLocaleLowerCase();
      const score = terms.reduce((total, term) => {
        if (!haystack.includes(term)) return -1000;
        return total + (item.title.toLocaleLowerCase().includes(term) ? 5 : 1);
      }, 0);
      return { ...item, score };
    })
    .filter((item) => item.score >= 0)
    .sort((a, b) => b.score - a.score || a.title.localeCompare(b.title))
    .slice(0, 20);

  searchResults.replaceChildren();
  if (!matches.length) {
    const empty = document.createElement("p");
    empty.textContent = `No preserved pages match “${searchInput.value.trim()}”.`;
    searchResults.append(empty);
    return;
  }

  matches.forEach((item) => {
    const link = document.createElement("a");
    link.href = item.url;
    const collection = document.createElement("span");
    collection.textContent = item.collection;
    const title = document.createElement("strong");
    title.textContent = item.title;
    link.append(collection, title);
    searchResults.append(link);
  });
});

const menuButton = document.querySelector(".menu-button");
const siteNav = document.querySelector("#site-nav");
menuButton?.addEventListener("click", () => {
  const open = menuButton.getAttribute("aria-expanded") === "true";
  menuButton.setAttribute("aria-expanded", String(!open));
  siteNav?.classList.toggle("open", !open);
});

const lightbox = document.querySelector("[data-lightbox]");
const lightboxImage = lightbox?.querySelector("img");
const lightboxCaption = lightbox?.querySelector("p");
document.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-lightbox-src]");
  if (!trigger || !lightbox || !lightboxImage || !lightboxCaption) return;
  lightboxImage.src = trigger.dataset.lightboxSrc;
  lightboxImage.alt = trigger.dataset.lightboxCaption || "";
  lightboxCaption.textContent = trigger.dataset.lightboxCaption || "";
  lightbox.showModal();
});

