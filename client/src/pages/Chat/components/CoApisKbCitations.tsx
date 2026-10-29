/**
 * CoApisKbCitations — 知识库引用来源卡片
 *
 * 后端 enrich_chat_context 检索知识库后，把引用列表挂到 completed 响应事件
 * 的 citations 字段；transformResponse 把它转成卡片注入最后一条助手消息。
 * 这里渲染「引用来源」折叠卡片：每条只显示原始资源本身 —— 文档名、所属
 * 知识库、定位（页码/段落）与原文片段。
 *
 * 不显示任何打分：相关度是后端的启发式估算值，包装成"相关度 100%"呈现
 * 给用户，等于把估算当承诺，用户会拿它质疑检索结果，且中文场景下这个
 * 数字本身就不稳定。排序判据留在后端，用户只看资源。
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
  meta?: {
    page_start?: number;
    para_index?: number;
    relevance?: number;
    cover?: number;
    retrieval_score?: number;
    low_relevance?: boolean;
  };
}

interface CardData {
  citations: Citation[];
}

/** 资源定位：页码 + 段落，有则显示，无则留空。 */
function locate(c: Citation): string {
  const parts: string[] = [];
  const page = c.meta?.page_start;
  const para = c.meta?.para_index;
  if (typeof page === 'number') parts.push(`第 ${page} 页`);
  if (typeof para === 'number') parts.push(`第 ${para} 段`);
  if (parts.length === 0 && typeof c.chunk_index === 'number') {
    parts.push(`第 ${c.chunk_index + 1} 条`);
  }
  return parts.join(' · ');
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
        <span className="kb-citations-title">引用来源 · {cites.length} 个资源</span>
        {open ? <DownOutlined className="kb-citations-caret" /> : <RightOutlined className="kb-citations-caret" />}
      </div>
      {open && (
        <div className="kb-citations-body">
          {cites.map((c, i) => {
            const loc = locate(c);
            return (
              <div
                className="kb-citation-item"
                key={`${c.kb_id}-${c.document_id}-${c.chunk_index}-${i}`}
              >
                <div className="kb-citation-top">
                  <span className="kb-citation-idx">[{i + 1}]</span>
                  <FileTextOutlined className="kb-citation-doc-icon" />
                  <span className="kb-citation-title">
                    {c.doc_title || c.document_id || '未命名文档'}
                  </span>
                  {c.kb_name && <span className="kb-citation-kb">{c.kb_name}</span>}
                  {loc && <span className="kb-citation-loc">{loc}</span>}
                </div>
                {c.snippet && <div className="kb-citation-snippet">{c.snippet}</div>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default CoApisKbCitations;
