import React from 'react';
import {CloudOutlined,GlobalOutlined} from '@ant-design/icons';
export default function PortalHeader({language,onLanguage,children}){
 return <header className="portal-header"><a className="portal-brand" href="/"><span className="brand-mark"><CloudOutlined/></span><div><strong>CPE334</strong><span>Student Cloud Portal</span></div></a><div className="flex items-center gap-3"><span className="hidden text-xs tracking-wide text-slate-400 md:block">SOFTWARE ENGINEERING · 2026</span><div className="language-switch" role="group" aria-label="Language / ภาษา"><GlobalOutlined className="language-switch-icon" aria-hidden="true"/><div className="language-switch-options">{[["en","EN","English"],["th","TH","ไทย"]].map(([value,label,name])=><button key={value} type="button" lang={value} aria-label={name} aria-pressed={language===value} onClick={()=>onLanguage(value)}>{label}</button>)}</div></div>{children}</div></header>;
}
