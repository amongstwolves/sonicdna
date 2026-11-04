import type { Meta } from "@/lib/api";
import {
  changedParams,
  COMPONENT_LABELS,
  formatLoss,
  loggedNotes,
  provenanceOf,
  renderNumber,
  type Entry,
} from "@/lib/runs";
import { ProvenanceChip } from "./Provenance";

export function StepDetail({
  entry,
  previous,
  meta,
}: {
  entry: Entry | null;
  previous: Entry | null;
  meta: Meta | null;
}) {
  if (!entry) {
    return (
      <section className="panel detail">
        <h2>Selected render</h2>
        <p className="muted">Nothing revealed yet.</p>
      </section>
    );
  }
  const notes = loggedNotes(entry);
  const changes = previous ? changedParams(previous.recipe, entry.recipe) : [];
  const components = entry.components ?? {};
  const weights = meta?.loss_weights ?? {};
  const contributions = Object.keys(components).map((name) => ({
    name,
    value: components[name] * (weights[name] ?? 0),
  }));
  const widest = Math.max(1e-9, ...contributions.map((c) => c.value));

  return (
    <section className="panel detail">
      <header>
        <h2>Render {renderNumber(entry)}</h2>
        <ProvenanceChip source={entry.source} />
        <span className="detail-loss">
          <small>normalized loss</small>
          <span className="mono">{formatLoss(entry.loss)}</span>
        </span>
      </header>
      <p className="muted">{provenanceOf(entry.source).description}.</p>

      {entry.failure ? (
        <div className="failure-box">
          <strong>This render failed</strong>
          <span>{entry.failure}</span>
        </div>
      ) : null}

      {notes.length > 0 ? (
        <dl className="notes">
          {notes.map((note) => (
            <div key={note.label}>
              <dt>{note.label}</dt>
              <dd>{note.text}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="no-notes">The log holds no hypothesis or reasoning for this render.</p>
      )}

      {contributions.length > 0 ? (
        <>
          <h3>What makes up this loss</h3>
          <ul className="components">
            {contributions.map(({ name, value }) => (
              <li key={name}>
                <span title={COMPONENT_LABELS[name]?.plain}>{COMPONENT_LABELS[name]?.label ?? name}</span>
                <span className="component-bar" aria-hidden="true">
                  <span style={{ transform: `scaleX(${value / widest})` }} />
                </span>
                <span className="mono">{formatLoss(value)}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {changes.length > 0 ? (
        <details className="changes">
          <summary>
            {changes.length} parameter{changes.length === 1 ? "" : "s"} changed from render{" "}
            {previous ? renderNumber(previous) : ""}
          </summary>
          <table>
            <tbody>
              {changes.map((change) => (
                <tr key={change.path}>
                  <th scope="row">{change.label}</th>
                  <td className="mono">{change.from}</td>
                  <td aria-hidden="true">→</td>
                  <td className="mono">{change.to}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ) : null}
    </section>
  );
}
