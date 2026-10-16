import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'C2A Protocol',
  description: 'Chat-to-Action (C2A) Interactive Message Protocol - Documentation',
  themeConfig: {
    nav: [
      { text: 'Home', link: '/' },
      { text: 'API Reference', link: '/api/reference' },
      { text: 'Integration Guide', link: '/integration/guide' }
    ],
    sidebar: {
      '/': [
        {
          text: 'Getting Started',
          items: [
            { text: 'Introduction', link: '/' },
            { text: 'Quick Start', link: '/getting-started/quick-start' }
          ]
        },
        {
          text: 'API Reference',
          items: [
            { text: 'Protocol Specification', link: '/api/reference' },
            { text: 'Python SDK', link: '/api/python-sdk' },
            { text: 'TypeScript/React SDK', link: '/api/typescript-react-sdk' }
          ]
        },
        {
          text: 'Integration',
          items: [
            { text: 'Enterprise Channels', link: '/integration/channels' },
            { text: 'Agent Frameworks', link: '/integration/agent-frameworks' }
          ]
        }
      ],
      '/api/': [
        {
          text: 'API Reference',
          items: [
            { text: 'Protocol Specification', link: '/api/reference' },
            { text: 'Python SDK', link: '/api/python-sdk' },
            { text: 'TypeScript/React SDK', link: '/api/typescript-react-sdk' }
          ]
        }
      ]
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/coapis-ai/coapis-c2a' }
    ]
  }
})
