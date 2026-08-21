// The Morning Brief — servizio della pagina.
//
// Supabase Storage conserva volentieri il file ma lo serve sempre come
// text/plain, per non prestare il proprio dominio a pagine di phishing.
// Questa funzione lo rilegge e lo restituisce come HTML vero.
//
// Conseguenza pratica: la funzione si distribuisce una volta sola. Gli
// aggiornamenti dell'app passano da pipeline/upload_app.py, che riscrive
// il file su Storage; qui non si tocca più niente.

const BUCKET = "brief-app";
const OBJECT = "index.html";
const TTL_MS = 60_000;

const SOURCE =
  `${Deno.env.get("SUPABASE_URL")}/storage/v1/object/public/${BUCKET}/${OBJECT}`;

// Le istanze restano vive qualche minuto fra una richiesta e l'altra:
// una cache breve evita di rileggere Storage a ogni apertura.
let cached: { html: string; at: number } | null = null;

Deno.serve(async (req: Request) => {
  if (req.method !== "GET" && req.method !== "HEAD") {
    return new Response("Metodo non consentito", {
      status: 405,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }

  try {
    if (!cached || Date.now() - cached.at > TTL_MS) {
      const res = await fetch(SOURCE, { cache: "no-store" });
      if (!res.ok) throw new Error(`Storage ha risposto ${res.status}`);
      cached = { html: await res.text(), at: Date.now() };
    }
  } catch (err) {
    if (!cached) {
      return new Response(
        "La pagina non è raggiungibile in questo momento. Riprova fra poco.",
        { status: 502, headers: { "content-type": "text/plain; charset=utf-8" } },
      );
    }
    // se Storage fa i capricci ma abbiamo una copia, serviamo quella
    console.error("Storage non raggiungibile, servo la copia in cache:", err);
  }

  return new Response(req.method === "HEAD" ? null : cached!.html, {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "public, max-age=300",
      "x-content-type-options": "nosniff",
    },
  });
});
