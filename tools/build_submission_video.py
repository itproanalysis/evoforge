"""Make an edited evidence-overview video from saved public production records.

This is an edited evidence walkthrough, never a live UI recording.
Prepare -> synthesize the scene WAV files -> render. No model/network calls.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import wave

from PIL import Image, ImageDraw, ImageFont

BG, INK, MUTED, BLUE = '#f2f4f6', '#191f28', '#6b7684', '#3182f6'
W, H = 1920, 1080
FONT = Path('C:/Windows/Fonts')


def font(size, bold=False, mono=False):
    return ImageFont.truetype(str(FONT / ('consola.ttf' if mono else 'seguisb.ttf' if bold else 'segoeui.ttf')), size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--live-evidence', type=Path, required=True)
    options = parser.parse_args()
    out = options.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    live = json.loads(options.live_evidence.read_text(encoding='utf-8'))
    assert live['run']['status'] == 'succeeded' and live['signed_proof']['verify']['ok']
    records = json.loads((options.snapshot/'performance.json').read_text(encoding='utf-8'))['history']
    by_id = {r['measurement_id']: r for r in records}
    before, after = by_id['m_847b4c5cf495'], by_id['m_33d90fbd0072']
    assert (before['passed'], after['passed'], before['n'], after['n']) == (22, 35, 36, 36)
    assert before['cost_cents'] == after['cost_cents'] == 96
    scenes = [('A result you can check.', 'EvoForge', 'EvoForge turns an AI-written patch into a result you can inspect and verify. Muse Spark remains the principal Builder. This edited walkthrough presents saved production evidence. It is not a live screen recording.'), ('One task. Two honest paths.', 'A multi-model system versus one model', 'EvoForge combines GPT and Gemini implementation plans, Muse Spark code, and an independent Claude Opus Critic. The Critic starts from the specification, without reading the planners. The other lane gets one Muse Spark response. Different allowances are disclosed; we do not call this a matched single-model comparison.'), ('Both passed. That matters.', 'Four models, verified in production', 'A keyless production request exercised all four models, PostgreSQL accounting, and the remote Runner. Both lanes passed all thirteen hidden checks. It was a tie. This proves the deployed path works, not that the system is more intelligent. The recorded run and signed certificate are public.'), ('Show every model cost.', 'Provider usage; Runner compute excluded', 'That run used ten cents for EvoForge and three cents for the single call. The shared acceptance Judge used thirteen more cents, for twenty-six cents of model API usage overall. These figures use provider token usage and configured rates. They are not a reconciled invoice and exclude Runner compute.'), ('Improve the process. Measure it.', 'A historical controlled experiment', 'Earlier, the same Muse Spark model improved from twenty-two to thirty-five of thirty-six sealed tasks when only the patch harness changed. The ninety-five percent intervals do not overlap, and each run cost ninety-six cents. This historical experiment demonstrates a measured harness gain. It is separate from the new four-model configuration.'), ('From patch to pull request.', 'A real median-function repair', 'The service also repaired a real median function. Two visible tests and three hidden tests passed, along with all three integrity gates. Pull request nine contains the code, tests, and proof link. It remains open. We do not count an open pull request as a merged, validated improvement.'), ('Verify the bytes yourself.', 'A public Ed25519 certificate', 'Anyone can check the result certificate using the published Ed25519 key. Offline verification accepts the original and rejects a modified verdict. The signature proves the integrity and provenance of the certificate bytes. It does not guarantee that the verifier can withstand a malicious candidate.'), ('Try it. No API key needed.', 'A working service, with visible limits', 'Open the public workspace, inspect the saved comparison, and follow its verification link. The default models run with server-managed keys. There is one shared project and a twenty-run daily quota. Per-user isolation and adversarial verifier hardening remain unfinished. Source code and the evidence are public.')]

    def text(draw, xy, value, size=32, color=INK, bold=False, width=None, spacing=12, mono=False):
        x,y=xy; f=font(size,bold,mono)
        words=value.split(); lines=[]; line=''
        for word in words:
            trial=(line+' '+word).strip()
            if width and draw.textlength(trial,font=f)>width and line:lines.append(line);line=word
            else:line=trial
        if line:lines.append(line)
        for line in lines:draw.text((x,y),line,font=f,fill=color);y+=size+spacing
        return y

    def box(draw, bounds, fill='white', radius=28):draw.rounded_rectangle(bounds, radius=radius, fill=fill)
    def metric(draw, x, label, value, note, color=INK):
        box(draw,(x,350,x+480,725));text(draw,(x+40,390),label,30,MUTED)
        text(draw,(x+36,450),value,100,color,True);text(draw,(x+40,630),note,26,MUTED,width=400)

    manifest=[]
    for i,(title,kicker,narration) in enumerate(scenes):
        image=Image.new('RGB',(W,H),BG);d=ImageDraw.Draw(image)
        text(d,(100,66),'EvoForge',30,INK,True)
        text(d,(1620,70),f'{i+1:02d} / {len(scenes):02d}',22,MUTED)
        text(d,(100,165),kicker.upper(),24,BLUE,True)
        text(d,(96,218),title,70,INK,True,width=1710)
        if i==0:
            text(d,(96,410),'Better code needs evidence.',72,INK,True,width=1550)
            text(d,(100,570),'Muse Spark builds. GPT + Gemini plan. Claude Opus checks.',34,MUTED)
            text(d,(100,680),'Working service. Recorded results. Visible limits.',36,BLUE,True)
        elif i==1:
            for x,name,steps in [(100,'EvoForge',['GPT + Gemini plans / Spark patch','Independent Opus Critic','Runner + evidence gates']), (990,'Single call',['One Builder response','Same patch tools','Same hidden judge'])]:
                box(d,(x,355,x+830,805));text(d,(x+40,390),name,40,BLUE if x==100 else INK,True)
                for n,step in enumerate(steps):text(d,(x+45,485+n*90),f'{n+1}.  {step}',31,INK)
            text(d,(100,830),'Multi-model system vs one Spark call. Allowances disclosed. No invented winner.',28,MUTED)
        elif i==2:
            for x,label,value,note,color in [(100,'EvoForge','13/13','All hidden checks passed',BLUE),(720,'Single Spark call','13/13','All hidden checks passed',INK),(1340,'Outcome','TIE','One deployment check',INK)]:metric(d,x,label,value,note,color)
            text(d,(100,790),'Recorded run: job_306819b0b688. No superiority claim.',34,INK,True)
        elif i==3:
            cost={'evoforge':live['run']['lanes']['evoforge']['cost_cents'],'single':live['run']['lanes']['single']['cost_cents'],'judge':live['run']['judge_cost_cents']}
            for x,label,value,note,color in [(100,'EvoForge',cost['evoforge'],'Model API usage',BLUE),(720,'Single call',cost['single'],'Model API usage',INK),(1340,'Shared judge',cost['judge'],'Additional to lane costs',INK)]:metric(d,x,label,f'{value}c',note,color)
            text(d,(100,790),'26c model API usage overall. Runner compute excluded. One recorded run.',34,MUTED)
        elif i==4:
            box(d,(100,350,1820,835))
            for y,label,passed,lo,hi,col in [(470,'Harness /1',22,.449,.752,INK),(660,'Harness /2',35,.858,.995,BLUE)]:
                text(d,(145,y-50),label,32,MUTED);text(d,(145,y+6),f'{passed}/36',52,col,True)
                left,right=600,1740
                d.line((left+(right-left)*lo,y,left+(right-left)*hi,y),fill=col,width=8)
                for v in [lo,hi]:d.line((left+(right-left)*v,y-14,left+(right-left)*v,y+14),fill=col,width=4)
                mid=left+(right-left)*passed/36;d.ellipse((mid-11,y-11,mid+11,y+11),fill=col)
                text(d,(left,y+40),f'95% Wilson interval: {lo*100:.1f}% - {hi*100:.1f}%',26,MUTED)
            text(d,(100,860),'Repeated experiment: same Muse Spark, same 36 tasks, one attempt, 96c per run.',27,MUTED)
        elif i==5:
            box(d,(100,350,1180,825));text(d,(140,395),'stats.py / median (illustrative excerpt)',30,MUTED,True)
            code=['ordered = sorted(xs)','n = len(ordered)','mid = n // 2','if n % 2 == 1:','    return ordered[mid]','return (ordered[mid - 1] + ordered[mid]) / 2']
            for n,line in enumerate(code):d.text((140,465+n*46),line,font=font(30,mono=True),fill=INK)
            box(d,(1230,350,1820,825));text(d,(1275,400),'PR #9',54,BLUE,True)
            for n,line in enumerate(['Visible tests  2/2','Hidden tests   3/3','Integrity gates PASS','Open / not merged']):text(d,(1275,505+n*66),line,28,INK)
        elif i==6:
            box(d,(100,350,1820,820));text(d,(145,400),'Certificate: '+live['signed_proof']['certificate_id'],38,INK,True)
            text(d,(145,500),'Original certificate',32,MUTED);text(d,(1280,500),'SIGNATURE VALID',32,BLUE,True)
            text(d,(145,580),'Altered verdict',32,MUTED);text(d,(1280,580),'REJECTED',32,INK,True)
            text(d,(145,700),'Provenance and integrity of bytes. Not an absolute safety guarantee.',29,MUTED)
        else:
            text(d,(100,420),'evoforge-web-230852112787.asia-northeast3.run.app',35,BLUE,True,width=1700)
            text(d,(100,530),'github.com/itproanalysis/evoforge',38,INK,True)
            text(d,(100,650),'Workspace   /   Replay   /   Performance   /   Verify',36,MUTED)
            text(d,(100,770),'Single shared project. 20 runs/day. No visitor API key required.',30,MUTED)
        text(d,(100,1008),'EDITED EVIDENCE WALKTHROUGH  /  RECORDED RUNS  /  31 OCT 2026',20,MUTED)
        path=out/f'scene-{i:02d}.png';image.save(path)
        manifest.append({'index':i,'title':title,'image':path.name,'audio':f'scene-{i:02d}.wav','narration':narration})
    (out/'scenes.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (out/'narration.txt').write_text('\n\n'.join(s['narration'] for s in manifest),encoding='utf-8')
    if not options.render:
        print(f'Prepared {len(manifest)} evidence scenes and narration.');return
    ffmpeg=shutil.which('ffmpeg');assert ffmpeg, 'ffmpeg unavailable'
    durations=[];parts=[];subtitles=[];start=0
    for s in manifest:
        with wave.open(str(out/s['audio'])) as wav: seconds=wav.getnframes()/wav.getframerate()
        duration=seconds+1.2;durations.append(duration);part=out/f'part-{s["index"]:02d}.mp4';parts.append(part)
        cmd=[ffmpeg,'-y','-loglevel','error','-loop','1','-i',str(out/s['image']),'-i',str(out/s['audio']),'-t',str(duration),'-r','30','-c:v','libx264','-preset','veryfast','-crf','20','-threads','2','-pix_fmt','yuv420p','-af','apad','-c:a','aac','-b:a','160k','-ar','48000',str(part)]
        subprocess.run(cmd,check=True)
        words=s['narration'].split();groups=[words[i:i+14] for i in range(0,len(words),14)]
        cursor=start
        for group in groups:
            length=seconds*len(group)/len(words);subtitles.append((cursor,cursor+length,' '.join(group)));cursor+=length
        start+=duration
    def clock(t):
        n=round(t*1000);return f'{n//3600000:02d}:{n//60000%60:02d}:{n//1000%60:02d},{n%1000:03d}'
    rate=1.16  # Keep the evidence overview below the three-minute submission target.
    subtitles=[(a/rate,b/rate,value) for a,b,value in subtitles]
    (out/'captions.en.srt').write_text('\n\n'.join(f'{n+1}\n{clock(a)} --> {clock(b)}\n{text}' for n,(a,b,text) in enumerate(subtitles))+'\n',encoding='utf-8')
    def ass_clock(t):
        n=round(t*100);return f'{n//360000}:{n//6000%60:02d}:{n//100%60:02d}.{n%100:02d}'
    ass='[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 0\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Segoe UI,30,&H00FFFFFF,&H00FFFFFF,&H003D3330,&H003D3330,0,0,0,0,100,100,0,0,3,10,0,2,120,120,120,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    ass+='\n'.join(f'Dialogue: 0,{ass_clock(a)},{ass_clock(b)},Default,,0,0,0,,{value}' for a,b,value in subtitles)+'\n'
    (out/'captions.en.ass').write_text(ass,encoding='utf-8')
    (out/'concat.txt').write_text('\n'.join("file '"+p.name+"'" for p in parts),encoding='utf-8')
    source=out/'evidence-source.mp4';final=out/'EvoForge_Evidence_Walkthrough.mp4'
    subprocess.run([ffmpeg,'-y','-loglevel','error','-f','concat','-safe','0','-i','concat.txt','-c','copy',str(source)],cwd=out,check=True)
    subprocess.run([ffmpeg,'-y','-loglevel','error','-i',str(source),'-vf',f'setpts=PTS/{rate},subtitles=captions.en.ass','-af',f'atempo={rate}','-r','30','-c:v','libx264','-preset','veryfast','-crf','20','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart',str(final)],cwd=out,check=True)
    (out/'video-manifest.json').write_text(json.dumps({'file':final.name,'duration_seconds':sum(durations)/rate,'resolution':[W,H],'fps':30,'scene_durations':[d/rate for d in durations],'kind':'Edited evidence walkthrough with saved production records; not a live UI recording','audio':'Synthetic English narration, Microsoft Zira; burned-in and separate English captions','source_run_id':'job_306819b0b688','historical_harness_experiment':'22/36 vs35/36; single Spark, 96 cents each','pending':'Portal format requirements and final submission receipt unavailable; not submitted'},indent=2),encoding='utf-8')
    print(f'Video: {final.name}; {sum(durations)/rate:.1f} seconds; edited evidence walkthrough.')


if __name__=='__main__':main()
