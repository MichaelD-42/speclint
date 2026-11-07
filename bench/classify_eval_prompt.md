Classify each item of a customer or system specification as `requirement` or `information`.

- `requirement`: a binding statement of what the system, a component or the supplier does, delivers or has, including a value it must meet. It counts even without "shall"/"muss", for example "The pump delivers 2 l/min at 3 bar", "Storage temperature: −20 °C to +60 °C", "Die Leuchte erreicht 500 lx in 1 m Abstand".
- `information`: everything that binds no one: headings, notes, rationale or background, explanations, examples, definitions and abbreviations, references to other documents, revision history, open points, comments, and descriptions of the existing situation.

Read the input JSON file (a list of objects with `id`, `lang`, `text`). Write a JSON object mapping every `id` to `"requirement"` or `"information"` to the output path, and nothing else. Judge each item on its own text. Do not read or write any other file.
