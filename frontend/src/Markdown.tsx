/**
 * Markdown renderer for assistant messages. Thin wrapper around react-markdown
 * + remark-gfm (tables, strikethrough, task lists). Links open in a new tab.
 */

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  children: string;
}

export function Markdown({ children }: Props) {
  return (
    <div className="ti-prose">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: (props) => (
            <a {...props} target="_blank" rel="noopener noreferrer">
              {props.children}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
