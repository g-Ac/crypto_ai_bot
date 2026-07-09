/**
 * Save/load da partida via AsyncStorage. GameState é JSON puro, então
 * serializa direto. Chave versionada pra permitir migração futura.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import type { GameState } from '../types/game';

const SAVE_KEY = 'empire:save:v1';

export async function salvarJogo(state: GameState): Promise<void> {
  try {
    await AsyncStorage.setItem(SAVE_KEY, JSON.stringify(state));
  } catch (e) {
    console.warn('Falha ao salvar partida:', e);
  }
}

export async function carregarJogo(): Promise<GameState | null> {
  try {
    const raw = await AsyncStorage.getItem(SAVE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as GameState;
    // Sanidade mínima: precisa ter cidade e facções.
    if (!parsed?.cidade || !Array.isArray(parsed.faccoes)) return null;
    return parsed;
  } catch (e) {
    console.warn('Falha ao carregar partida:', e);
    return null;
  }
}

export async function existeSave(): Promise<boolean> {
  try {
    const raw = await AsyncStorage.getItem(SAVE_KEY);
    return !!raw;
  } catch {
    return false;
  }
}

export async function apagarSave(): Promise<void> {
  try {
    await AsyncStorage.removeItem(SAVE_KEY);
  } catch (e) {
    console.warn('Falha ao apagar save:', e);
  }
}
