declare module 'react-syntax-highlighter' {
  import { ComponentType } from 'react';
  
  export interface SyntaxHighlighterProps {
    language?: string;
    style?: object;
    customStyle?: object;
    showLineNumbers?: boolean;
    startingLineNumber?: number;
    lineNumberContainerStyle?: object;
    lineNumberStyle?: object;
    wrapLines?: boolean;
    wrapLongLines?: boolean;
    lineProps?: object | ((lineNumber: number) => object);
    codeTagProps?: object;
    useInlineStyles?: boolean;
    showInlineLineNumbers?: boolean;
    children: string;
  }
  
  export const Prism: ComponentType<SyntaxHighlighterProps>;
  export const PrismLight: ComponentType<SyntaxHighlighterProps> & {
    registerLanguage: (name: string, language: unknown) => void;
  };
  export const Light: ComponentType<SyntaxHighlighterProps>;
}

declare module 'react-syntax-highlighter/dist/esm/languages/prism/*' {
  const language: unknown;
  export default language;
}

declare module 'react-syntax-highlighter/dist/esm/styles/prism/*' {
  const style: object;
  export default style;
}
