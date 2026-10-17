import {
  BookOpen, CarFront, CircleDot, CircleQuestionMark, Compass, Crosshair, Dices, Footprints, GraduationCap, Grid3x3,
  HandFist, Layers, type LucideIcon, MessageCircleQuestion, Music, Plane, Puzzle, Rocket, Shapes, Swords, Castle,
  Trophy, WandSparkles, Zap,
} from "lucide-react";

/** Picto de chaque genre (clés de app.services.genres.GENRES). */
export const GENRE_ICONS: Record<string, LucideIcon> = {
  action: Zap,
  aventure: Compass,
  beat: HandFist,
  combat: Swords,
  course: CarFront,
  plateforme: Footprints,
  rpg: WandSparkles,
  shmup: Rocket,
  tir: Crosshair,
  sport: Trophy,
  reflexion: Puzzle,
  labyrinthe: Grid3x3,
  strategie: Castle,
  simulation: Plane,
  flipper: CircleDot,
  societe: Dices,
  quiz: MessageCircleQuestion,
  musique: Music,
  educatif: GraduationCap,
  compilation: Layers,
  autre: Shapes,
  none: CircleQuestionMark,
};

export const genreIcon = (key: string | null | undefined): LucideIcon => GENRE_ICONS[key ?? "none"] ?? BookOpen;
