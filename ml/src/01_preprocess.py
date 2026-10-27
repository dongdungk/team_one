import csv
import json
import datetime
import pathlib
import pandas as pd
import numpy as np

def parse_wazuh_csv(csv_path, label, session_id):
    """
    Wazuh OpenSearch에서 다운로드한 CSV (timestamp, full_log)를 파싱하여
    개별 HTTP 요청 레코드 리스트로 반환합니다.
    """
    records = []
    with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if len(row) < 2:
                continue
            raw_log = row[1]
            try:
                data = json.loads(raw_log)
                # 타임스탬프 파싱 (ISO 8601 포맷)
                ts_str = data.get('timestamp')
                if not ts_str:
                    continue
                # 2026-10-26T06:16:37+09:00 형태 파싱
                dt = datetime.datetime.fromisoformat(ts_str)
                
                # 이미지/정적 리소스 필터링
                path = data.get('path', '')
                if any(path.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.css', '.js', '.ico', '.woff', '.woff2']):
                    continue
                
                records.append({
                    'timestamp': dt,
                    'client_ip': data.get('client_ip', 'unknown'),
                    'method': data.get('method', 'GET'),
                    'path': path,
                    'status': int(data.get('status', 200)),
                    'response_bytes': int(data.get('response_bytes', 0)),
                    'duration_ms': float(data.get('duration_ms', 0.0)),
                    'user_agent': data.get('user_agent', ''),
                    'label': label,
                    'session_id': session_id
                })
            except Exception as e:
                pass
                
    return records

def extract_30s_window_features(records, window_seconds=30):
    """
    HTTP 요청 레코드 리스트를 클라이언트 IP별, 30초 시간 창(Window) 단위로 묶어
    머신러닝 학습용 8대 행동 특징값(Feature)을 계산합니다.
    """
    if not records:
        return pd.DataFrame()
        
    df_raw = pd.DataFrame(records)
    # 시간순 정렬
    df_raw = df_raw.sort_values('timestamp').reset_index(drop=True)
    
    # 세션 내 최소/최대 시간
    start_time = df_raw['timestamp'].min()
    end_time = df_raw['timestamp'].max()
    
    features_list = []
    
    # IP별로 그룹화하여 30초 창 분할
    for ip, ip_group in df_raw.groupby('client_ip'):
        session_label = ip_group['label'].iloc[0]
        session_id = ip_group['session_id'].iloc[0]
        
        # 30초 단위 시간 슬롯 생성
        curr_window_start = start_time
        window_idx = 0
        
        while curr_window_start <= end_time:
            curr_window_end = curr_window_start + datetime.timedelta(seconds=window_seconds)
            
            # 현재 30초 창에 속하는 로그 필터링
            window_df = ip_group[(ip_group['timestamp'] >= curr_window_start) & (ip_group['timestamp'] < curr_window_end)]
            
            req_count = len(window_df)
            
            # 로그가 발생한 창만 샘플로 생성 (또는 최소 1건 이상 발생한 구간)
            if req_count > 0:
                # 1. 요청 간격(interval) 계산
                if req_count > 1:
                    timestamps = window_df['timestamp'].values
                    # 나노초 단위를 초(float) 단위로 변환
                    intervals = np.diff(timestamps).astype('float64') / 1e9
                    interval_mean = float(np.mean(intervals))
                    interval_std = float(np.std(intervals))
                else:
                    interval_mean = float(window_seconds)
                    interval_std = 0.0
                
                # 2. 상태코드 비율 (404, 422, 500 등 비정상/에러 비율)
                error_404_count = len(window_df[window_df['status'] == 404])
                error_404_ratio = error_404_count / req_count
                
                error_abnormal_count = len(window_df[window_df['status'] >= 400])
                error_abnormal_ratio = error_abnormal_count / req_count
                
                # 3. 고유 URL 및 User-Agent 수
                unique_url_count = window_df['path'].nunique()
                unique_ua_count = window_df['user_agent'].nunique()
                
                # 4. POST 요청 비율
                post_count = len(window_df[window_df['method'] == 'POST'])
                ratio_post = post_count / req_count
                
                # 5. 평균 응답 바이트 크기
                bytes_mean = float(window_df['response_bytes'].mean())
                
                features_list.append({
                    'session_id': session_id,
                    'window_idx': window_idx,
                    'client_ip': ip,
                    'window_start': curr_window_start.strftime('%Y-%m-%d %H:%M:%S'),
                    'req_count': req_count,
                    'interval_mean': round(interval_mean, 4),
                    'interval_std': round(interval_std, 4),
                    'error_404_ratio': round(error_404_ratio, 4),
                    'error_abnormal_ratio': round(error_abnormal_ratio, 4),
                    'unique_url_count': unique_url_count,
                    'unique_ua_count': unique_ua_count,
                    'ratio_post': round(ratio_post, 4),
                    'bytes_mean': round(bytes_mean, 2),
                    'label': session_label  # 0: 정상, 1: PentAGI
                })
                
            curr_window_start = curr_window_end
            window_idx += 1
            
    return pd.DataFrame(features_list)

def main():
    base_dir = pathlib.Path(r"d:\Project\ML")
    raw_dir = base_dir / "data" / "raw_logs"
    out_dir = base_dir / "data"
    
    print("=" * 60)
    print("[Wazuh 원본 로그 -> 30초 창 머신러닝 특징값 변환 시작]")
    print("=" * 60)
    
    all_features = []
    
    # raw_logs 디렉토리 내의 모든 CSV 파일 순회
    csv_files = list(raw_dir.glob("*.csv"))
    if not csv_files:
        print("[ERROR] 처리할 CSV 파일이 raw_logs 폴더에 없습니다.")
        return
        
    for f in csv_files:
        fname = f.name.lower()
        # 파일명 기반 라벨 및 세션 ID 자동 판별
        if "attack" in fname or "pentagi" in fname:
            label = 1
            s_type = "공격(PentAGI)"
        else:
            label = 0
            s_type = "정상(Human)"
            
        session_id = f.stem
        print(f"[FILE] 처리 중: {f.name} -> 분류: {s_type} (Label={label})")
        
        records = parse_wazuh_csv(f, label=label, session_id=session_id)
        df_feat = extract_30s_window_features(records, window_seconds=30)
        
        if not df_feat.empty:
            print(f"   - 30초 시간 창 샘플 {len(df_feat)}개 추출 완료!")
            all_features.append(df_feat)
        else:
            print("   - 유효한 데이터가 없습니다.")
            
    if all_features:
        final_df = pd.concat(all_features, ignore_index=True)
        out_csv = out_dir / "features_dataset.csv"
        final_df.to_csv(out_csv, index=False, encoding='utf-8-sig')
        print("\n" + "=" * 60)
        print(f"[SUCCESS] [성공] 머신러닝 학습용 최종 데이터셋 저장 완료: {out_csv}")
        print(f"총 추출된 30초 창 샘플 수: {len(final_df)}개")
        print("클래스별 샘플 분포:")
        print(final_df['label'].value_counts().rename({0: '정상(0)', 1: '공격(1)'}))
        print("=" * 60)
        print("\n[PREVIEW] 추출된 데이터 미리보기 (상위 5행):")
        display_cols = ['session_id', 'window_start', 'req_count', 'interval_std', 'error_404_ratio', 'unique_url_count', 'label']
        print(final_df[display_cols].head())

if __name__ == "__main__":
    main()
