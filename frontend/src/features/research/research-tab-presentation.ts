import type { ResearchTab } from "@/features/research/research-navigation";

type ResearchTabPresentation = {
  context: string;
  description: string;
  title: string;
};

const researchTabPresentations: Record<ResearchTab, ResearchTabPresentation> = {
  independent: {
    context: "Ricerca manuale",
    title: "Ricerca indipendente",
    description:
      "Interroga gli indexer senza applicare le regole automatiche delle richieste Jellyseerr.",
  },
  summary: {
    context: "Workflow richieste",
    title: "Ricerche e riepilogo",
    description:
      "Avvia la ricerca automatica, controlla l'avanzamento e gestisci le richieste trovate.",
  },
  rules: {
    context: "Configurazione ricerca",
    title: "Regole di ricerca",
    description:
      "Definisci le regole condivise e i valori iniziali della ricerca indipendente.",
  },
  requests: {
    context: "Richieste Jellyseerr",
    title: "Richieste monitorate",
    description:
      "Aggiorna le richieste Jellyseerr e gestisci le eccezioni di ricerca per ogni contenuto.",
  },
};

function researchTabPresentation(tab: ResearchTab) {
  return researchTabPresentations[tab];
}

export { researchTabPresentation };
