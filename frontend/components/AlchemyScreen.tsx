"use client";

import { useState } from "react";

const PRESERVE = ["Pitch", "Rhythm", "Envelope"];

export function AlchemyScreen() {
  const [prompt, setPrompt] = useState("");
  const [preserved, setPreserved] = useState<string[]>(["Pitch"]);

  return (
    <div className="alchemy">
      <div className="not-connected" role="status">
        <strong>Not yet connected</strong>
        <span>
          Alchemy has no backend in this build. Nothing here runs, and the slots below stay empty
          until it does. Nothing on this page is a result.
        </span>
      </div>

      <div className="alchemy-grid">
        <section className="panel">
          <small className="eyebrow">Screen preview</small>
          <h1>Transform a recovered recipe.</h1>
          <label className="field">
            <span>Describe the change</span>
            <textarea
              rows={3}
              value={prompt}
              placeholder="brighter and more atmospheric, keep the pitch"
              onChange={(event) => setPrompt(event.target.value)}
            />
          </label>
          <fieldset className="field">
            <legend>Keep these the same</legend>
            <div className="row">
              {PRESERVE.map((name) => (
                <label key={name} className="toggle">
                  <input
                    type="checkbox"
                    checked={preserved.includes(name)}
                    onChange={(event) =>
                      setPreserved((current) =>
                        event.target.checked
                          ? [...current, name]
                          : current.filter((item) => item !== name),
                      )
                    }
                  />
                  {name}
                </label>
              ))}
            </div>
          </fieldset>
          <button type="button" className="button button-primary" disabled>
            Generate variations (not connected)
          </button>
        </section>

        <section aria-label="Variation cards">
          <h2 className="section-title">Variations</h2>
          <div className="variation-grid">
            {[1, 2, 3].map((slot) => (
              <article key={slot} className="variation-card">
                <small className="eyebrow">Slot {slot}</small>
                <p>Empty. No variation has been generated.</p>
              </article>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
