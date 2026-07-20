import { useState, useRef, useCallback } from 'react';
import { api } from '../services/api';
import Icon from '../components/Icon';
import styles from './ResumeUpload.module.css';

export default function ResumeUpload({ onSuccess }) {
  const [file, setFile]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState('');
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  const handleFile = useCallback((f) => {
    if (!f) return;
    const ext = f.name.split('.').pop().toLowerCase();
    if (!['pdf', 'txt', 'md'].includes(ext)) {
      setError('Only PDF, TXT, or MD files are supported.');
      return;
    }
    if (f.size > 10 * 1024 * 1024) {
      setError('File too large. Max 10 MB.');
      return;
    }
    setError('');
    setFile(f);
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    handleFile(e.dataTransfer.files[0]);
  }, [handleFile]);

  const handleSubmit = async () => {
    if (!file) return;
    setLoading(true);
    setError('');
    try {
      const result = await api.uploadResume(file);
      onSuccess(result);
    } catch (e) {
      setError(e.message || 'Upload failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      <div className="fade-up">
        <h2 className={styles.title}>Upload your resume</h2>
        <p className={styles.sub}>
          We'll parse your background and generate questions tailored to you and the role.
        </p>
      </div>

      <div
        className={`${styles.dropzone} ${dragging ? styles.dragging : ''} ${file ? styles.hasFile : ''} fade-up-1`}
        onDrop={handleDrop}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onClick={() => !file && inputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label="Upload resume"
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.txt,.md"
          style={{ display: 'none' }}
          onChange={(e) => handleFile(e.target.files[0])}
        />

        {file ? (
          <div className={styles.filePreview}>
            <div className={styles.fileIconWrap}>
              <Icon name="document" size={20} />
            </div>
            <div className={styles.fileInfo}>
              <span className={styles.fileName}>{file.name}</span>
              <span className={styles.fileSize}>{(file.size / 1024).toFixed(1)} KB</span>
            </div>
            <button
              className={styles.removeBtn}
              onClick={(e) => { e.stopPropagation(); setFile(null); }}
              aria-label="Remove file"
            >
              <Icon name="close" size={14} />
            </button>
          </div>
        ) : (
          <div className={styles.placeholder}>
            <div className={styles.uploadIconWrap}>
              <Icon name="upload" size={26} />
            </div>
            <p className={styles.dropText}>
              {dragging ? 'Drop it here' : 'Drag & drop your resume'}
            </p>
            <p className={styles.hint}>PDF, TXT or Markdown · Max 10 MB</p>
            <button
              className={styles.browseBtn}
              onClick={(e) => { e.stopPropagation(); inputRef.current?.click(); }}
            >
              <Icon name="paperClip" size={14} />
              Browse files
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className={`${styles.error} fade-up`}>
          <Icon name="exclamationTriangle" size={15} />
          {error}
        </div>
      )}

      <button
        id="upload-resume-btn"
        className={`${styles.submitBtn} fade-up-2`}
        disabled={!file || loading}
        onClick={handleSubmit}
      >
        {loading ? (
          <><span className="spinner" /> Analysing resume…</>
        ) : (
          <>Continue <Icon name="arrowRight" size={16} /></>
        )}
      </button>
    </div>
  );
}
