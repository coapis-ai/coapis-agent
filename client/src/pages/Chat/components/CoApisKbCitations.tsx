/**
 * CoApisKbCitations — 引用来源卡片（知识库 + 本轮注入的记忆）
 *
 * 后端 enrich_chat_context 检索知识库后，把引用列表挂到 completed 响应事件
 * 的 citations 字段；transformResponse 把它转成卡片注入最后一条助手消息。
 * 这里渲染「引用来源」折叠卡片：每条只显示原始资源本身 —— 文档名、所属
 * 知识库、定位（页码/段落）与原文片段。
 *
 * 不显示任何打分：相关度是后端的启发式估算值，包装成"相关度 100%"呈现
 * 给用户，等于把估算当承诺，用户会拿它质疑检索结果，且中文场景下这个
 * 数字本身就不稳定。排序判据留在后端，用户只看资源。
 * （例外：kind=memory 的条目显示相关度——它是本轮实际注入的记忆，用户需要
 * 知道"系统凭什么挑了这条"，并且要能就地撤销。）
 *
 * v3 知识沉淀：kind==="memory" 的条目是本轮注入到上下文里的沉淀记忆，
 * 带「撤销」入口——看见机器替我做了什么，并且当场能撤。
 *
 * 设计遵循 DESIGN_SPEC：默认折叠（极简），点开看明细（按需复杂）。
 */
import React, { useState } from 'react';
import {
  BookOutlined,
  FileTextOutlined,
  DownOutlined,
  RightOutlined,
  HistoryOutlined,
} from '@ant-design/icons';
import { Popconfirm, message } from 'antd';
import { undoMemoryKnowledge } from '../../../api/modules/memory';
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
  /** v3: "memory" = 本轮注入的沉淀记忆；缺省 = 知识库引用 */
  kind?: string;
  /** v3: 记忆条目形如 "memory:<id>" */
  resource_id?: string;
  /** v3: 记忆条目的相关度（本轮注入排序依据） */
  relevance?: number;
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

/** 从 "memory:<id>" 里取记忆 id；取不到返回 null（不给撤销按钮）。 */
function memoryIdOf(c: Citation): number | null {
  const raw = String(c.resource_id || '');
  if (!raw.startsWith('memory:')) return null;
  const id = Number(raw.slice('memory:'.length));
  return Number.isFinite(id) && id > 0 ? id : null;
}

const CoApisKbCitations: React.FC<{ data: CardData }> = ({ data }) => {
  const cites = data?.citations;
  const [open, setOpen] = useState(false);
  // 撤销成功后本地消失（citations 是只读 props，靠这份集合过滤）
  const [undoneIds, setUndoneIds] = useState<Set<string>>(new Set());
  const [undoing, setUndoing] = useState<number | null>(null);

  if (!cites || cites.length === 0) return null;

  const visible = cites.filter((c) => {
    const key = c.resource_id || `${c.kb_id}-${c.document_id}-${c.chunk_index}`;
    return !undoneIds.has(key);
  });
  if (visible.length === 0) return null;

  const handleUndo = async (c: Citation) => {
    const id = memoryIdOf(c);
    if (id === null) {
      message.error('无法定位这条记忆');
      return;
    }
    setUndoing(id);
    try {
      await undoMemoryKnowledge(id);
      setUndoneIds((prev) => {
        const next = new Set(prev);
        next.add(c.resource_id || `memory:${id}`);
        return next;
      });
      message.success('已撤销这条记忆');
    } catch (e: any) {
      message.error(e?.message || '撤销失败');
    } finally {
      setUndoing(null);
    }
  };

  return (
    <div className="kb-citations">
      <div
        className="kb-citations-header"
        onClick={() => setOpen((v) => !v)}
        role="button"
        tabIndex={0}
      >
        <BookOutlined className="kb-citations-icon" />
        <span className="kb-citations-title">引用来源 · {visible.length} 个资源</span>
        {open ? <DownOutlined className="kb-citations-caret" /> : <RightOutlined className="kb-citations-caret" />}
      </div>
      {open && (
        <div className="kb-citations-body">
          {visible.map((c, i) => {
            // ── 本轮注入的沉淀记忆：可就地撤销，不给「打开资源」 ──
            if (c.kind === 'memory') {
              const id = memoryIdOf(c);
              return (
                <div
                  className="kb-citation-item kb-citation-memory"
                  key={c.resource_id || `memory-${id}-${i}`}
                >
                  <div className="kb-citation-top">
                    <span className="kb-citation-idx">[{i + 1}]</span>
                    <HistoryOutlined className="kb-citation-doc-icon" />
                    <span className="kb-citation-title">
                      {c.doc_title || '记忆'}
                    </span>
                    <span className="kb-citation-kb">记忆</span>
                    {typeof c.relevance === 'number' && (
                      <span className="kb-citation-loc">
                        相关度 {c.relevance.toFixed(2)}
                      </span>
                    )}
                    <Popconfirm
                      title="撤销这条记忆？"
                      description="撤销后不再注入，可在进化中心恢复。"
                      okText="撤销"
                      cancelText="取消"
                      okButtonProps={{ danger: true, loading: undoing === id }}
                      onConfirm={() => handleUndo(c)}
                    >
                      <a
                        className="kb-citation-undo"
                        style={{ fontSize: 12 }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        撤销
                      </a>
                    </Popconfirm>
                  </div>
                  {c.snippet && (
                    <div
                      className="kb-citation-snippet"
                      style={{
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {c.snippet}
                    </div>
                  )}
                </div>
              );
            }

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
