/**
 * ChatErrorBoundary — 错误边界组件，捕获React渲染错误
 */
import React from 'react';
import { Result, Button } from 'antd';

interface Props {
  children: React.ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

class ChatErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('[ChatErrorBoundary] Caught error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <Result
          status="warning"
          title="页面出现异常"
          subTitle={this.state.error?.message || '加载聊天内容时发生错误'}
          extra={[
            <Button 
              key="reload" 
              type="primary" 
              onClick={() => {
                this.setState({ hasError: false });
                window.location.reload();
              }}
            >
              刷新页面
            </Button>,
            <Button 
              key="clear" 
              onClick={() => {
                // Clear chat data and reload
                localStorage.removeItem('chatSessions');
                this.setState({ hasError: false });
                window.location.reload();
              }}
            >
              清除缓存并刷新
            </Button>,
          ]}
        />
      );
    }

    return this.props.children;
  }
}

export default ChatErrorBoundary;
