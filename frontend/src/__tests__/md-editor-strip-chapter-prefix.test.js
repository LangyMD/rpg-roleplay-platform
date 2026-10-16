import { describe, it, expect } from 'vitest';
import { stripChapterPrefix } from '../components/md-editor/helpers.js';

describe('stripChapterPrefix', () => {
  it('strips the Chinese ordinal prefix', () => {
    expect(stripChapterPrefix('第5章 雨夜')).toBe('雨夜');
  });

  it('strips the English "Chapter N" / "Ch. N" prefix shown by the English UI', () => {
    expect(stripChapterPrefix('Chapter 5: The Duel')).toBe('The Duel');
    expect(stripChapterPrefix('Ch. 3 Dawn')).toBe('Dawn');
  });

  it('leaves titles that merely start with the word alone', () => {
    expect(stripChapterPrefix('Chapters of Life')).toBe('Chapters of Life');
    expect(stripChapterPrefix('Chaptered')).toBe('Chaptered');
  });
});
