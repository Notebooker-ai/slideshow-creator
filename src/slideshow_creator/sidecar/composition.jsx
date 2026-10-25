import React from 'react';
import {AbsoluteFill, Composition, Img, Sequence, interpolate, registerRoot, useCurrentFrame} from 'remotion';

export const FRAMES_PER_SLIDE = 180;
export function Slide({slide, index, total, theme}) {
  const frame = useCurrentFrame();
  const dark = ['dark', 'moon', 'night', 'league', 'blood'].includes(theme);
  const ink = dark ? '#f4f8f6' : '#18352e';
  const muted = dark ? '#b8cec5' : '#4c6960';
  return <AbsoluteFill style={{background: dark ? '#102a23' : '#f6faf7', color: ink, padding: '72px 92px', fontFamily: 'Arial, sans-serif'}}>
    <div style={{display:'flex', justifyContent:'space-between', fontSize:23, color:muted, letterSpacing:3}}><span>NOTEBOOKER</span><span>LEARN · CONNECT · REMEMBER</span></div>
    <div style={{height:5, width:110, background:'#29a77c', marginTop:27}}/>
    <div data-slide-content style={{flex:1, display:'flex', flexDirection:'column', justifyContent:'center', opacity:interpolate(frame,[0,14],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'}), translate:`0 ${interpolate(frame,[0,18],[16,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'})}px`}}>
      <h1 style={{fontSize:slide.type === 'title' ? 72 : 54, lineHeight:1.12, letterSpacing:-1.8, margin:'0 0 32px', maxWidth:1650}}>{slide.title}</h1>
      {slide.subtitle && <p style={{fontSize:36, lineHeight:1.4, color:muted, margin:'0 0 24px'}}>{slide.subtitle}</p>}
      {slide.visual && <Img src={slide.visual} style={{maxHeight:560, maxWidth:'100%', objectFit:'contain', alignSelf:'center'}}/>}
      {!slide.visual && slide.body && <p style={{fontSize:35, lineHeight:1.45, margin:'0 0 24px', maxWidth:1550}}>{slide.body}</p>}
      {!slide.visual && slide.bullets?.length > 0 && <ul style={{fontSize:35, lineHeight:1.45, paddingLeft:42, margin:0}}>{slide.bullets.map((bullet,i)=><li key={i} style={{paddingLeft:12, marginBottom:20}}>{bullet}</li>)}</ul>}
      {slide.caption && <p style={{fontSize:25, lineHeight:1.4, color:muted, margin:'20px 0 0'}}>{slide.caption}</p>}
    </div>
    <div style={{display:'flex', justifyContent:'space-between', fontSize:22, color:muted, borderTop:`1px solid ${dark?'#36564a':'#d1dfd6'}`, paddingTop:20}}><span>notebooker.ai</span><span>{String(index+1).padStart(2,'0')} / {String(total).padStart(2,'0')}</span></div>
  </AbsoluteFill>;
}
export function Deck({slides, theme}) {
  return <AbsoluteFill>{slides.map((slide,index)=><Sequence key={index} from={index*FRAMES_PER_SLIDE} durationInFrames={FRAMES_PER_SLIDE}><Slide slide={slide} index={index} total={slides.length} theme={theme}/></Sequence>)}</AbsoluteFill>;
}
registerRoot(()=> <Composition id="NotebookerSlideshow" component={Deck} width={1920} height={1080} fps={30} durationInFrames={180} defaultProps={{slides:[{type:'title',title:'Notebooker'}],theme:'light'}} calculateMetadata={({props})=>({durationInFrames:props.slides.length*FRAMES_PER_SLIDE})}/>);
