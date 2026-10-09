/**
 * CoApisKbCitations — 知识库引用来源卡片
 *
 * 后端 enrich_chat_context 检索知识库后，把引用列表挂到 completed 响应事件
 * 的 citations 字段；transformResponse 把它转成卡片注入最后一条助手消息。
 * 这里渲染「来源」折叠卡片：每条显示文档标题、知识库名、分片、评分与摘要片段。
 *
 * 设计遵循 DESIGN_SPEC：默认折叠（极简），点开看明细（按需复杂）。
 */
import React, { useState } from 'react';
import { BookOutlined, FileTextOutlined, DownOutlined, RightOutlined } from '@ant-design/icons';
import './CoApisKbCitations.module.less';

interface Citation {
  kb_id: string;
  kb_name?: string;
  document_id?: string;
  doc_title?: string;
  chunk_index?: number;
  snippet?: string;
  score?: number;
  chunk_id?: string;
}

interface CardData {
  citations: Citation[];
}

const CoApisKbCitations: React.FC<{ data: CardData }> = ({ data }) => {
  const cites = data?.citations;
  const [open, setOpen] = useState(false);

  if (!cites || cites.length === 0) return null;

  return (
    <div className="kb-citations">
      <div
        className="kb-citations-header"
        onClick={() => setOpen((v) => !v)}
        role="button"
        tabIndex={0}
      >
        <BookOutlined className="kb-citations-icon" />
        <span className="kb-citations-title">知识库引用 · {cites.length} 条来源</span>
        {open ? <DownOutlined className="kb-citations-caret" /> : <RightOutlined className="kb-citations-caret" />}
      </div>
      {open && (
        <div className="kb-citations-body">
          {cites.map((c, i) => (
            <div className="kb-citation-item" key={`${c.kb_id}-${c.document_id}-${c.chunk_index}-${i}`}>
              <div className="kb-citation-top">
                <span className="kb-citation-idx">[{i + 1}]</span>
                <FileTextOutlined className="kb-citation-doc-icon" />
                <span className="kb-citation-title">
                  {c.doc_title || c.document_id || '未命名文档'}
                </span>
                {c.kb_name && <span className="kb-citation-kb">{c.kb_name}</span>}
                {typeof c.score === 'number' && (
                  <span className="kb-citation-score">{c.score.toFixed(2)}</span>
                )}
              </div>
              {c.snippet && <div className="kb-citation-snippet">{c.snippet}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default CoApisKbCitations;
